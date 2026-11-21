import os
import random
import smtplib
from email.message import EmailMessage
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, render_template, redirect, url_for, request, flash, abort, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from models import (
    db, User, PasswordOTP, Attendance, TestScore,
    StudyMaterial, DoubtTicket, QuestionBank, Notice,
    OnlineExam, ExamMCQ, ExamAttempt
)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'flourish-forge-du-cs-secret-2026')
uri = os.environ.get('DATABASE_URL', 'sqlite:///flourish_forge.db')
if uri.startswith('postgres://'):
    uri = uri.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['FACULTY_FOLDER'] = os.path.join(app.root_path, 'static', 'faculty')

# Email SMTP configuration (optional via Environment Variables)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', '587'))
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_FROM'] = os.environ.get('MAIL_FROM') or os.environ.get('MAIL_USERNAME') or 'noreply@flourishforge.in'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['FACULTY_FOLDER'], exist_ok=True)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

CLASSES_7_TO_12 = ['Class 7', 'Class 8', 'Class 9', 'Class 10', 'Class 11', 'Class 12']
NCERT_OFFICIAL_LINKS = [
    {"class_name": "Class 8", "title": "NCERT Official Textbooks - Class 8", "url": "https://ncert.nic.in/textbook.php?hesc1=0-13"},
    {"class_name": "Class 9", "title": "NCERT Official Textbooks - Class 9", "url": "https://ncert.nic.in/textbook.php?iesc1=0-12"},
    {"class_name": "Class 10", "title": "NCERT Official Textbooks - Class 10", "url": "https://ncert.nic.in/textbook.php?jesc1=0-13"},
    {"class_name": "All Classes", "title": "NCERT Official E-Book Portal (Classes 7-12)", "url": "https://ncert.nic.in/textbook.php"},
]

ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'txt', 'ppt', 'pptx',
    'png', 'jpg', 'jpeg', 'gif', 'webp'
}
IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def build_auto_mcq(target_class, subject, chapter, idx, difficulty='Medium'):
    templates_mcq = [
        (
            f"In '{chapter}' ({target_class} {subject}), which principle is applied directly in NCERT problems? (Q{idx})",
            "Standard NCERT definition and verified formula",
            "Ignoring boundary conditions and units",
            "Assuming arbitrary constants without proof",
            "None of the above",
            "A",
            "Standard NCERT definition and verified formula"
        ),
        (
            f"Which step is essential first when solving a board question from '{chapter}' ({target_class} {subject})? (Q{idx})",
            "Identify given data, units, and applicable theorem",
            "Skip intermediate reasoning steps",
            "Substitute unrelated chapter formulas",
            "Approximate values before final step",
            "A",
            "Identify given data, units, and applicable theorem"
        ),
        (
            f"For '{chapter}' in {target_class} {subject}, what ensures full marks in CBSE evaluation? (Q{idx})",
            "Logical step-by-step derivation with correct unit/result",
            "Writing only a rough guess",
            "Omitting key conditions",
            "Leaving the final conclusion blank",
            "A",
            "Logical step-by-step derivation with correct unit/result"
        ),
        (
            f"Which statement best describes the core concept of '{chapter}' ({subject}, {target_class})? (Q{idx})",
            "It connects foundational axioms to problem-solving applications",
            "It has no numerical or conceptual application",
            "It applies only outside the CBSE curriculum",
            "It contradicts standard laws",
            "A",
            "It connects foundational axioms to problem-solving applications"
        ),
    ]
    qt, oa, ob, oc, od, corr, ans_txt = templates_mcq[(idx - 1) % len(templates_mcq)]
    return QuestionBank(
        target_class=target_class,
        subject=subject,
        chapter=chapter,
        question_type='MCQ',
        difficulty=difficulty,
        marks=1,
        question_text=qt,
        option_a=oa,
        option_b=ob,
        option_c=oc,
        option_d=od,
        answer_key=f"({corr}) {ans_txt}"
    )


def build_auto_subjective(target_class, subject, chapter, idx, difficulty='Medium'):
    marks_map = {'Easy': 2, 'Medium': 3, 'HOTS': 5}
    m = marks_map.get(difficulty, 3)
    if difficulty == 'Easy':
        qt = f"[{chapter}] State two core definitions or properties from '{chapter}' in {target_class} {subject} with a clear example. (Q{idx})"
        ak = f"Write exact NCERT definition/property for '{chapter}' and illustrate with one valid example."
    elif difficulty == 'Medium':
        qt = f"[{chapter}] Explain the key theorem/method in '{chapter}' ({target_class} {subject}) step-by-step with a solved illustration. (Q{idx})"
        ak = f"Present structured steps, governing formula/law from '{chapter}', and verified final answer."
    else:
        qt = f"[{chapter} - HOTS] Solve and justify a higher-order application problem based on '{chapter}' in {target_class} {subject}. (Q{idx})"
        ak = f"Identify governing condition in '{chapter}', execute multi-step reasoning, and state final conclusion."

    return QuestionBank(
        target_class=target_class,
        subject=subject,
        chapter=chapter,
        question_type='Subjective',
        difficulty=difficulty,
        marks=m,
        question_text=qt,
        answer_key=ak
    )


def pick_exact_questions(pool, requested_count, maker_fn):
    # Strictly returns exact requested_count items - never more, never fewer.
    if requested_count <= 0:
        return []
    pool_copy = list(pool)
    random.shuffle(pool_copy)
    selected = pool_copy[:requested_count]
    auto_idx = 1
    while len(selected) < requested_count:
        selected.append(maker_fn(auto_idx))
        auto_idx += 1
    return selected[:requested_count]


def send_otp_email(to_email, otp_code):
    mail_user = app.config['MAIL_USERNAME']
    mail_pass = app.config['MAIL_PASSWORD']
    if not mail_user or not mail_pass:
        return False, "SMTP credentials not configured in environment variables."
    try:
        msg = EmailMessage()
        msg['Subject'] = 'Flourish Forge Portal - Password Reset OTP'
        msg['From'] = app.config['MAIL_FROM']
        msg['To'] = to_email
        msg.set_content(
            "Hello,\n\n"
            f"Your One-Time Password (OTP) to reset your Flourish Forge Portal password is: {otp_code}\n"
            "This OTP is valid for 10 minutes.\n\n"
            "Regards,\nFlourish Forge (Director: Shivam Tiwari)"
        )
        with smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT'], timeout=15) as server:
            server.starttls()
            server.login(mail_user, mail_pass)
            server.send_message(msg)
        return True, "OTP sent to your registered email address."
    except Exception as e:
        return False, f"Email delivery failed: {str(e)}"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


with app.app_context():
    db.create_all()
    admin_email = os.environ.get('ADMIN_EMAIL', 'director@flourishforge.in').strip().lower()
    admin_password = os.environ.get('ADMIN_PASSWORD', 'flourishforge123')
    admin = User.query.filter_by(role='admin').first()
    if not admin:
        admin = User(
            name='Shivam Tiwari',
            email=admin_email,
            role='admin',
            subject_specialty='Mathematics & Science',
            qualification='B.Sc. (Hons.) Computer Science, University of Delhi',
            experience_years=3,
            bio='Director & Lead Mentor at Flourish Forge for CBSE Classes 7-12.'
        )
        admin.set_password(admin_password)
        db.session.add(admin)

    if QuestionBank.query.count() == 0:
        seed_qs = [
            QuestionBank(target_class='Class 10', subject='Mathematics', chapter='Quadratic Equations',
                         question_type='MCQ', difficulty='Easy', marks=1,
                         question_text='If 1/2 is a root of x^2 + kx - 5/4 = 0, then k equals:',
                         option_a='2', option_b='-2', option_c='1/4', option_d='1/2', answer_key='(A) 2'),
            QuestionBank(target_class='Class 10', subject='Mathematics', chapter='Polynomials',
                         question_type='MCQ', difficulty='Easy', marks=1,
                         question_text='The zeroes of x^2 + 99x + 127 are:',
                         option_a='Both positive', option_b='Both negative', option_c='One positive, one negative', option_d='Equal',
                         answer_key='(B) Both negative'),
            QuestionBank(target_class='Class 10', subject='Mathematics', chapter='Arithmetic Progressions',
                         question_type='MCQ', difficulty='Easy', marks=1,
                         question_text='10th term of AP: 5, 8, 11, 14, ... is:',
                         option_a='32', option_b='35', option_c='29', option_d='38',
                         answer_key='(A) 32'),
            QuestionBank(target_class='Class 10', subject='Mathematics', chapter='Real Numbers',
                         question_type='Subjective', difficulty='Medium', marks=3,
                         question_text='[CBSE PYQ] Prove that sqrt(2) is an irrational number.',
                         answer_key='Proof by contradiction assuming sqrt(2) = p/q in lowest terms.'),
            QuestionBank(target_class='Class 10', subject='Science', chapter='Chemical Reactions and Equations',
                         question_type='Subjective', difficulty='Easy', marks=2,
                         question_text='[CBSE PYQ] Why should a magnesium ribbon be cleaned before burning in air?',
                         answer_key='To remove surface oxide/carbonate layer so combustion proceeds cleanly.'),
            QuestionBank(target_class='Class 9', subject='Mathematics', chapter='Number Systems',
                         question_type='MCQ', difficulty='Easy', marks=1,
                         question_text='[PYQ] Express 0.666... in p/q form:',
                         option_a='6/10', option_b='2/3', option_c='1/3', option_d='6/99',
                         answer_key='(B) 2/3'),
            QuestionBank(target_class='Class 9', subject='Science', chapter='Matter in Our Surroundings',
                         question_type='MCQ', difficulty='Easy', marks=1,
                         question_text='[PYQ] Convert 300 K into Celsius scale:',
                         option_a='27 deg C', option_b='573 deg C', option_c='273 deg C', option_d='30 deg C',
                         answer_key='(A) 27 deg C'),
            QuestionBank(target_class='Class 8', subject='Mathematics', chapter='Linear Equations in One Variable',
                         question_type='Subjective', difficulty='Easy', marks=2,
                         question_text='[PYQ] Solve: (2x - 3) / (3x + 2) = -2/3.',
                         answer_key='x = 5/12'),
            QuestionBank(target_class='Class 8', subject='Science', chapter='Force and Pressure',
                         question_type='MCQ', difficulty='Easy', marks=1,
                         question_text='[PYQ] Pressure is defined as:',
                         option_a='Force x Area', option_b='Force / Area', option_c='Area / Force', option_d='Mass / Volume',
                         answer_key='(B) Force / Area'),
        ]
        db.session.add_all(seed_qs)

    if OnlineExam.query.count() == 0:
        demo_exam = OnlineExam(
            title='Class 10 Maths - Quick Practice Quiz (5 MCQs)',
            target_class='Class 10',
            subject='Mathematics',
            chapter='Quadratic Equations & AP',
            created_by='Flourish Forge'
        )
        db.session.add(demo_exam)
        db.session.flush()
        demo_mcqs = [
            ExamMCQ(exam_id=demo_exam.id, question_text='Discriminant D of ax^2 + bx + c = 0 is:',
                    option_a='b^2 - 4ac', option_b='b^2 + 4ac', option_c='4ac - b^2', option_d='2ab', correct_option='A', marks=1),
            ExamMCQ(exam_id=demo_exam.id, question_text='If D = 0 for a quadratic equation, roots are:',
                    option_a='Real and equal', option_b='Distinct real', option_c='No real roots', option_d='Imaginary', correct_option='A', marks=1),
            ExamMCQ(exam_id=demo_exam.id, question_text='Common difference of AP 2, 7, 12, 17, ... is:',
                    option_a='3', option_b='5', option_c='7', option_d='2', correct_option='B', marks=1),
            ExamMCQ(exam_id=demo_exam.id, question_text='Sum of first n natural numbers is:',
                    option_a='n(n+1)/2', option_b='n(n-1)/2', option_c='n^2', option_d='2n', correct_option='A', marks=1),
            ExamMCQ(exam_id=demo_exam.id, question_text='Roots of x^2 - 9 = 0 are:',
                    option_a='+3 and -3', option_b='9 and -9', option_c='0 and 9', option_d='1 and 9', correct_option='A', marks=1),
        ]
        db.session.add_all(demo_mcqs)

    db.session.commit()


# ---------------- AUTH & OTP ROUTES ----------------
@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(f"{current_user.role}_dashboard"))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for(f"{user.role}_dashboard"))
        flash('Invalid Email or Password. Please try again.', 'danger')
    return render_template('login.html')


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        action = request.form.get('action', 'send_otp')
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()

        if action == 'send_otp':
            if not user:
                flash('No account found with that email address.', 'warning')
                return render_template('forgot_password.html', email=email, otp_sent=False)

            otp_code = f"{random.randint(100000, 999999)}"
            otp_entry = PasswordOTP(
                email=email,
                otp_code=otp_code,
                expires_at=datetime.utcnow() + timedelta(minutes=10),
                used=False
            )
            db.session.add(otp_entry)
            db.session.commit()
            session['reset_email'] = email

            sent, status_msg = send_otp_email(email, otp_code)
            if sent:
                flash('A 6-digit OTP has been sent to your email. Valid for 10 minutes.', 'success')
            else:
                flash(
                    f"OTP generated for {email} (SMTP not set: {status_msg}). "
                    f"Instant Verification OTP: {otp_code}",
                    'info'
                )
            return render_template('forgot_password.html', email=email, otp_sent=True)

        elif action == 'reset_password':
            otp_input = request.form.get('otp_code', '').strip()
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

            if not user:
                flash('Invalid email account.', 'danger')
                return render_template('forgot_password.html', email=email, otp_sent=True)

            if len(new_password) < 6:
                flash('New password must be at least 6 characters long.', 'warning')
                return render_template('forgot_password.html', email=email, otp_sent=True)

            if new_password != confirm_password:
                flash('New password and confirm password do not match.', 'warning')
                return render_template('forgot_password.html', email=email, otp_sent=True)

            otp_rec = PasswordOTP.query.filter_by(
                email=email, otp_code=otp_input, used=False
            ).order_by(PasswordOTP.id.desc()).first()

            if not otp_rec or not otp_rec.is_valid():
                flash('Invalid or expired OTP. Please request a new OTP.', 'danger')
                return render_template('forgot_password.html', email=email, otp_sent=True)

            otp_rec.used = True
            user.set_password(new_password)
            db.session.commit()
            session.pop('reset_email', None)
            flash('Password updated successfully! You can now sign in with your new password.', 'success')
            return redirect(url_for('login'))

    saved_email = session.get('reset_email', '')
    return render_template('forgot_password.html', email=saved_email, otp_sent=bool(saved_email))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ---------------- ADMIN ROUTES ----------------
@app.route('/admin')
@login_required
@role_required('admin')
def admin_dashboard():
    teachers = User.query.filter_by(role='teacher').all()
    students = User.query.filter_by(role='student').all()
    notices = Notice.query.order_by(Notice.created_at.desc()).all()
    return render_template(
        'admin_dashboard.html',
        classes=CLASSES_7_TO_12,
        teachers=teachers,
        students=students,
        notices=notices,
        ncert_links=NCERT_OFFICIAL_LINKS
    )


@app.route('/admin/add_user', methods=['POST'])
@login_required
@role_required('admin')
def add_user():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    role = request.form.get('role')
    student_class = request.form.get('student_class') if role == 'student' else None
    batch_timing = request.form.get('batch_timing') if role == 'student' else None
    subject_specialty = request.form.get('subject_specialty') if role == 'teacher' else None

    if User.query.filter_by(email=email).first():
        flash('Email already registered!', 'warning')
    else:
        new_user = User(
            name=name,
            email=email,
            role=role,
            student_class=student_class,
            batch_timing=batch_timing,
            subject_specialty=subject_specialty
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash(f'{role.capitalize()} account created for {name}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/reset_password', methods=['POST'])
@login_required
@role_required('admin')
def reset_password():
    user_id = int(request.form.get('user_id'))
    new_pass = request.form.get('new_password')
    user = db.get_or_404(User, user_id)
    user.set_password(new_pass)
    db.session.commit()
    flash(f'Password reset successfully for {user.name}.', 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/add_notice', methods=['POST'])
@login_required
@role_required('admin')
def add_notice():
    notice = Notice(
        title=request.form.get('title'),
        message=request.form.get('message'),
        target_class=request.form.get('target_class', 'All Classes')
    )
    db.session.add(notice)
    db.session.commit()
    flash('Announcement published to portal!', 'success')
    return redirect(url_for('admin_dashboard'))


# ---------------- TEACHER ROUTES ----------------
@app.route('/teacher')
@login_required
@role_required('teacher', 'admin')
def teacher_dashboard():
    students = User.query.filter_by(role='student').all()
    faculty_list = User.query.filter(User.role.in_(['teacher', 'admin'])).order_by(
        User.experience_years.desc().nullslast(), User.id.asc()
    ).all()
    materials = StudyMaterial.query.order_by(StudyMaterial.uploaded_at.desc()).all()
    doubts = DoubtTicket.query.order_by(DoubtTicket.created_at.desc()).all()
    exams = OnlineExam.query.order_by(OnlineExam.created_at.desc()).all()

    filter_cls = request.args.get('filter_class', '')
    filter_sub = request.args.get('filter_subject', '').strip()
    filter_chap = request.args.get('filter_chapter', '').strip()
    q_query = QuestionBank.query
    if filter_cls:
        q_query = q_query.filter_by(target_class=filter_cls)
    if filter_sub:
        q_query = q_query.filter(QuestionBank.subject.ilike(f"%{filter_sub}%"))
    if filter_chap:
        q_query = q_query.filter(QuestionBank.chapter.ilike(f"%{filter_chap}%"))
    questions = q_query.order_by(QuestionBank.id.desc()).all()

    return render_template(
        'teacher_dashboard.html',
        classes=CLASSES_7_TO_12,
        students=students,
        materials=materials,
        doubts=doubts,
        questions=questions,
        exams=exams,
        filter_cls=filter_cls,
        filter_sub=filter_sub,
        filter_chap=filter_chap,
        faculty_list=faculty_list,
        ncert_links=NCERT_OFFICIAL_LINKS,
        today_str=date.today().isoformat()
    )


@app.route('/teacher/update_profile', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def update_teacher_profile():
    name = request.form.get('name', '').strip()
    subject_specialty = request.form.get('subject_specialty', '').strip()
    qualification = request.form.get('qualification', '').strip()
    exp_raw = request.form.get('experience_years', '').strip()
    bio = request.form.get('bio', '').strip()

    if name:
        current_user.name = name
    if subject_specialty:
        current_user.subject_specialty = subject_specialty
    if qualification:
        current_user.qualification = qualification
    if exp_raw != '':
        try:
            current_user.experience_years = max(0, int(exp_raw))
        except ValueError:
            pass
    if bio:
        current_user.bio = bio

    photo = request.files.get('profile_photo')
    if photo and photo.filename:
        if not allowed_image(photo.filename):
            flash('Please upload a valid photo (PNG, JPG, JPEG, GIF, WEBP).', 'warning')
            return redirect(url_for('teacher_dashboard'))
        safe_photo = secure_filename(photo.filename)
        unique_photo = f"faculty_{current_user.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe_photo}"
        photo.save(os.path.join(app.config['FACULTY_FOLDER'], unique_photo))
        current_user.profile_photo = unique_photo

    db.session.commit()
    flash('Faculty profile updated (optional).', 'success')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/mark_attendance', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def mark_attendance():
    att_date_str = request.form.get('att_date') or date.today().isoformat()
    att_date_obj = datetime.strptime(att_date_str, '%Y-%m-%d').date()
    students = User.query.filter_by(role='student').all()
    count = 0
    for s in students:
        status = request.form.get(f'status_{s.id}')
        if status in ('Present', 'Absent'):
            existing = Attendance.query.filter_by(student_id=s.id, att_date=att_date_obj).first()
            if existing:
                existing.status = status
                existing.marked_by = current_user.name
            else:
                db.session.add(Attendance(
                    student_id=s.id,
                    att_date=att_date_obj,
                    status=status,
                    marked_by=current_user.name
                ))
            count += 1
    db.session.commit()
    flash(f'Attendance saved for {count} students on {att_date_str}.', 'success')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/add_score', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def add_score():
    marks_obtained = float(request.form.get('marks_obtained'))
    max_marks = float(request.form.get('max_marks'))
    score = TestScore(
        student_id=int(request.form.get('student_id')),
        subject=request.form.get('subject'),
        chapter=request.form.get('chapter'),
        marks_obtained=marks_obtained,
        max_marks=max_marks,
        remarks=request.form.get('remarks')
    )
    db.session.add(score)
    db.session.commit()
    flash('Test marks published!', 'success')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/upload_material', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def upload_material():
    file = request.files.get('file')
    if file and file.filename:
        if not allowed_file(file.filename):
            flash('Unsupported file type.', 'warning')
            return redirect(url_for('teacher_dashboard'))
        safe_name = secure_filename(file.filename)
        unique_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe_name}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
        mat = StudyMaterial(
            title=request.form.get('title'),
            target_class=request.form.get('target_class'),
            subject=request.form.get('subject'),
            filename=unique_name,
            uploaded_by=current_user.name
        )
        db.session.add(mat)
        db.session.commit()
        flash('Study material / photo uploaded successfully!', 'success')
    else:
        flash('Please select a file or photo to upload.', 'warning')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/resolve_doubt/<int:doubt_id>', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def resolve_doubt(doubt_id):
    doubt = db.get_or_404(DoubtTicket, doubt_id)
    doubt.answer = request.form.get('answer')
    doubt.status = 'Resolved'
    db.session.commit()
    flash('Doubt resolved and sent to student!', 'success')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/add_question', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def add_question():
    q_type = request.form.get('question_type', 'Subjective')
    q = QuestionBank(
        target_class=request.form.get('target_class'),
        subject=request.form.get('subject', '').strip(),
        chapter=request.form.get('chapter', '').strip(),
        question_type=q_type,
        difficulty=request.form.get('difficulty'),
        marks=int(request.form.get('marks', 1 if q_type == 'MCQ' else 2)),
        question_text=request.form.get('question_text'),
        option_a=request.form.get('option_a') if q_type == 'MCQ' else None,
        option_b=request.form.get('option_b') if q_type == 'MCQ' else None,
        option_c=request.form.get('option_c') if q_type == 'MCQ' else None,
        option_d=request.form.get('option_d') if q_type == 'MCQ' else None,
        answer_key=request.form.get('answer_key')
    )
    db.session.add(q)
    db.session.commit()
    flash(f'{q_type} question added to Question Bank!', 'success')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/auto_generate_chapter_bank', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def auto_generate_chapter_bank():
    target_class = request.form.get('target_class')
    subject = request.form.get('subject', '').strip()
    chapters_raw = request.form.get('chapters', '').strip()
    mcq_n = max(0, int(request.form.get('mcq_count', 0)))
    subj_n = max(0, int(request.form.get('subj_count', 0)))

    chapter_list = [c.strip() for c in chapters_raw.split(',') if c.strip()] or ['General Chapter']
    added_count = 0
    for ch in chapter_list:
        for i in range(1, mcq_n + 1):
            db.session.add(build_auto_mcq(target_class, subject, ch, i, 'Medium'))
            added_count += 1
        for j in range(1, subj_n + 1):
            db.session.add(build_auto_subjective(target_class, subject, ch, j, 'Medium'))
            added_count += 1
    db.session.commit()
    flash(f'Auto-generated {added_count} chapter-wise questions across {len(chapter_list)} chapter(s) in Question Bank!', 'success')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/edit_question/<int:q_id>', methods=['GET', 'POST'])
@login_required
@role_required('teacher', 'admin')
def edit_question(q_id):
    q = db.get_or_404(QuestionBank, q_id)
    if request.method == 'POST':
        q.target_class = request.form.get('target_class')
        q.subject = request.form.get('subject', '').strip()
        q.chapter = request.form.get('chapter', '').strip()
        q.question_type = request.form.get('question_type', 'Subjective')
        q.difficulty = request.form.get('difficulty')
        q.marks = int(request.form.get('marks', 1))
        q.question_text = request.form.get('question_text')
        if q.question_type == 'MCQ':
            q.option_a = request.form.get('option_a')
            q.option_b = request.form.get('option_b')
            q.option_c = request.form.get('option_c')
            q.option_d = request.form.get('option_d')
        else:
            q.option_a = q.option_b = q.option_c = q.option_d = None
        q.answer_key = request.form.get('answer_key')
        db.session.commit()
        flash('Question updated successfully!', 'success')
        return redirect(url_for('teacher_dashboard'))
    return render_template('edit_question.html', q=q, classes=CLASSES_7_TO_12)


@app.route('/teacher/delete_question/<int:q_id>', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def delete_question(q_id):
    q = db.get_or_404(QuestionBank, q_id)
    db.session.delete(q)
    db.session.commit()
    flash('Question removed from Question Bank.', 'info')
    return redirect(url_for('teacher_dashboard'))


@app.route('/teacher/generate_paper', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def generate_paper():
    target_class = request.form.get('target_class')
    subject = request.form.get('subject', '').strip()
    chapters_raw = request.form.get('chapters', '').strip()
    exam_title = request.form.get('exam_title') or 'Chapter-Wise Assessment Test'
    duration = request.form.get('duration') or '1 Hour 30 Mins'

    # Strict exact counts enforced
    mcq_n = max(0, int(request.form.get('mcq_count', 0)))
    subj_n = max(0, int(request.form.get('subj_count', 0)))

    chapter_list = [c.strip() for c in chapters_raw.split(',') if c.strip()]
    primary_chapter = chapter_list[0] if chapter_list else 'Full Syllabus'

    base_q = QuestionBank.query.filter(
        QuestionBank.target_class == target_class,
        QuestionBank.subject.ilike(f"%{subject}%")
    )
    if chapter_list:
        chap_clauses = [QuestionBank.chapter.ilike(f"%{ch}%") for ch in chapter_list]
        base_q = base_q.filter(db.or_(*chap_clauses))

    mcq_pool = base_q.filter_by(question_type='MCQ').all()
    subj_pool = base_q.filter_by(question_type='Subjective').all()

    selected_mcqs = pick_exact_questions(
        mcq_pool, mcq_n,
        lambda idx: build_auto_mcq(target_class, subject, chapter_list[(idx - 1) % len(chapter_list)] if chapter_list else primary_chapter, idx)
    )
    selected_subj = pick_exact_questions(
        subj_pool, subj_n,
        lambda idx: build_auto_subjective(target_class, subject, chapter_list[(idx - 1) % len(chapter_list)] if chapter_list else primary_chapter, idx)
    )

    all_selected = selected_mcqs + selected_subj
    total_marks = sum(q.marks for q in all_selected)
    chapter_display = ", ".join(chapter_list) if chapter_list else "All Chapters"

    return render_template(
        'generated_paper.html',
        target_class=target_class,
        subject=subject,
        chapter_display=chapter_display,
        exam_title=exam_title,
        duration=duration,
        mcqs=selected_mcqs,
        subjectives=selected_subj,
        all_questions=all_selected,
        total_marks=total_marks,
        today=date.today().strftime('%d-%b-%Y')
    )


@app.route('/teacher/create_online_exam', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def create_online_exam():
    title = request.form.get('title', '').strip() or 'Online MCQ Test'
    target_class = request.form.get('target_class')
    subject = request.form.get('subject', '').strip()
    chapter = request.form.get('chapter', '').strip() or 'Chapter Test'
    mcq_count = max(1, min(50, int(request.form.get('mcq_count', 20))))
    bulk_text = request.form.get('bulk_mcqs', '').strip()

    exam = OnlineExam(
        title=title,
        target_class=target_class,
        subject=subject,
        chapter=chapter,
        created_by=current_user.name
    )
    db.session.add(exam)
    db.session.flush()

    parsed_mcqs = []
    if bulk_text:
        for line in bulk_text.splitlines():
            line = line.strip()
            if not line or '|' not in line:
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 6:
                corr = parts[5].upper()[:1]
                if corr not in ('A', 'B', 'C', 'D'):
                    corr = 'A'
                parsed_mcqs.append(ExamMCQ(
                    exam_id=exam.id,
                    question_text=parts[0],
                    option_a=parts[1],
                    option_b=parts[2],
                    option_c=parts[3],
                    option_d=parts[4],
                    correct_option=corr,
                    marks=1
                ))

    bank_mcqs = QuestionBank.query.filter(
        QuestionBank.target_class == target_class,
        QuestionBank.subject.ilike(f"%{subject}%"),
        QuestionBank.question_type == 'MCQ',
        QuestionBank.option_a.isnot(None),
        QuestionBank.option_b.isnot(None),
        QuestionBank.option_c.isnot(None),
        QuestionBank.option_d.isnot(None)
    ).all()
    random.shuffle(bank_mcqs)

    for bq in bank_mcqs:
        if len(parsed_mcqs) >= mcq_count:
            break
        ans_raw = (bq.answer_key or 'A').strip().upper()
        corr = 'A'
        for ch_let in ('A', 'B', 'C', 'D'):
            if ans_raw.startswith(ch_let) or f"({ch_let})" in ans_raw:
                corr = ch_let
                break
        parsed_mcqs.append(ExamMCQ(
            exam_id=exam.id,
            question_text=bq.question_text,
            option_a=bq.option_a,
            option_b=bq.option_b,
            option_c=bq.option_c,
            option_d=bq.option_d,
            correct_option=corr,
            marks=1
        ))

    auto_num = 1
    while len(parsed_mcqs) < mcq_count:
        gen_q = build_auto_mcq(target_class, subject, chapter, auto_num)
        ans_raw = (gen_q.answer_key or 'A').strip().upper()
        corr = 'B' if '(B)' in ans_raw else ('C' if '(C)' in ans_raw else ('D' if '(D)' in ans_raw else 'A'))
        parsed_mcqs.append(ExamMCQ(
            exam_id=exam.id,
            question_text=gen_q.question_text,
            option_a=gen_q.option_a,
            option_b=gen_q.option_b,
            option_c=gen_q.option_c,
            option_d=gen_q.option_d,
            correct_option=corr,
            marks=1
        ))
        auto_num += 1

    final_mcqs = parsed_mcqs[:mcq_count]
    db.session.add_all(final_mcqs)
    db.session.commit()
    flash(f'Online MCQ Exam "{title}" published with exact {len(final_mcqs)} MCQs for {target_class}!', 'success')
    return redirect(url_for('teacher_dashboard'))


# ---------------- STUDENT ROUTES ----------------
@app.route('/student')
@login_required
@role_required('student')
def student_dashboard():
    scores = TestScore.query.filter_by(student_id=current_user.id).order_by(TestScore.id.desc()).all()
    attempts = ExamAttempt.query.filter_by(student_id=current_user.id).order_by(ExamAttempt.submitted_at.desc()).all()
    available_exams = OnlineExam.query.filter(
        (OnlineExam.target_class == current_user.student_class) | (OnlineExam.target_class.is_(None))
    ).order_by(OnlineExam.created_at.desc()).all()
    if not available_exams:
        available_exams = OnlineExam.query.order_by(OnlineExam.created_at.desc()).all()

    attendance_records = Attendance.query.filter_by(student_id=current_user.id).order_by(Attendance.att_date.desc()).all()
    present_days = sum(1 for a in attendance_records if a.status == 'Present')
    total_days = len(attendance_records)
    att_pct = round((present_days / total_days) * 100, 1) if total_days > 0 else 0.0

    faculty_list = User.query.filter(User.role.in_(['teacher', 'admin'])).order_by(
        User.experience_years.desc().nullslast(), User.id.asc()
    ).all()
    materials = StudyMaterial.query.filter_by(target_class=current_user.student_class).order_by(StudyMaterial.uploaded_at.desc()).all()
    doubts = DoubtTicket.query.filter_by(student_id=current_user.id).order_by(DoubtTicket.created_at.desc()).all()
    notices = Notice.query.filter(
        (Notice.target_class == 'All Classes') | (Notice.target_class == current_user.student_class)
    ).order_by(Notice.created_at.desc()).all()

    return render_template(
        'student_dashboard.html',
        scores=scores,
        attempts=attempts,
        available_exams=available_exams,
        materials=materials,
        doubts=doubts,
        notices=notices,
        faculty_list=faculty_list,
        ncert_links=NCERT_OFFICIAL_LINKS,
        present_days=present_days,
        total_days=total_days,
        att_pct=att_pct
    )


@app.route('/student/exam/<int:exam_id>', methods=['GET', 'POST'])
@login_required
@role_required('student')
def attempt_exam(exam_id):
    exam = db.get_or_404(OnlineExam, exam_id)
    if request.method == 'POST':
        correct_cnt = 0
        earned_marks = 0
        total_marks = sum(q.marks for q in exam.questions)
        for q in exam.questions:
            chosen = request.form.get(f'q_{q.id}', '').strip().upper()
            if chosen == q.correct_option:
                correct_cnt += 1
                earned_marks += q.marks

        total_q = len(exam.questions)
        pct = round((earned_marks / total_marks) * 100, 1) if total_marks > 0 else 0.0

        attempt = ExamAttempt(
            exam_id=exam.id,
            student_id=current_user.id,
            score=earned_marks,
            total_marks=total_marks,
            correct_count=correct_cnt,
            total_questions=total_q,
            percentage=pct
        )
        db.session.add(attempt)

        db.session.add(TestScore(
            student_id=current_user.id,
            subject=exam.subject,
            chapter=exam.chapter,
            marks_obtained=earned_marks,
            max_marks=total_marks,
            remarks=f"Online MCQ Exam: {exam.title} ({correct_cnt}/{total_q} correct)"
        ))
        db.session.commit()
        flash(f'Exam submitted! Auto-generated score: {earned_marks}/{total_marks} ({pct}%)', 'success')
        return redirect(url_for('exam_result', attempt_id=attempt.id))

    return render_template('attempt_exam.html', exam=exam)


@app.route('/student/exam-result/<int:attempt_id>')
@login_required
@role_required('student')
def exam_result(attempt_id):
    attempt = db.get_or_404(ExamAttempt, attempt_id)
    if attempt.student_id != current_user.id:
        abort(403)
    return render_template('exam_result.html', attempt=attempt)


@app.route('/student/ask_doubt', methods=['POST'])
@login_required
@role_required('student')
def ask_doubt():
    doubt = DoubtTicket(
        student_id=current_user.id,
        subject=request.form.get('subject'),
        question=request.form.get('question')
    )
    db.session.add(doubt)
    db.session.commit()
    flash('Doubt submitted to faculty!', 'success')
    return redirect(url_for('student_dashboard'))


if __name__ == '__main__':
    app.run(debug=True)
