import os
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'admin', 'teacher', 'student'
    student_class = db.Column(db.String(15), nullable=True)  # 'Class 7' .. 'Class 12'
    batch_timing = db.Column(db.String(50), nullable=True)
    subject_specialty = db.Column(db.String(80), nullable=True)
    qualification = db.Column(db.String(150), nullable=True)
    experience_years = db.Column(db.Integer, nullable=True, default=0)
    bio = db.Column(db.Text, nullable=True)
    profile_photo = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class PasswordOTP(db.Model):
    __tablename__ = 'password_otps'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    otp_code = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_valid(self):
        return (not self.used) and (datetime.utcnow() <= self.expires_at)


class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    att_date = db.Column(db.Date, default=date.today, nullable=False)
    status = db.Column(db.String(15), nullable=False)  # 'Present' or 'Absent'
    marked_by = db.Column(db.String(100), nullable=False)

    student = db.relationship('User', backref='attendance_records')


class TestScore(db.Model):
    __tablename__ = 'test_scores'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject = db.Column(db.String(50), nullable=False)
    chapter = db.Column(db.String(100), nullable=False)
    marks_obtained = db.Column(db.Float, nullable=False)
    max_marks = db.Column(db.Float, nullable=False)
    remarks = db.Column(db.String(200))
    date_recorded = db.Column(db.Date, default=date.today)

    student = db.relationship('User', backref='scores')


class StudyMaterial(db.Model):
    __tablename__ = 'study_materials'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    target_class = db.Column(db.String(15), nullable=False)
    subject = db.Column(db.String(50), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    uploaded_by = db.Column(db.String(100), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_image(self):
        ext = os.path.splitext(self.filename.lower())[1]
        return ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp')


class DoubtTicket(db.Model):
    __tablename__ = 'doubt_tickets'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    subject = db.Column(db.String(50), nullable=False)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='Open')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship('User', backref='doubts')


class QuestionBank(db.Model):
    __tablename__ = 'question_bank'
    id = db.Column(db.Integer, primary_key=True)
    target_class = db.Column(db.String(15), nullable=False)
    subject = db.Column(db.String(50), nullable=False)
    chapter = db.Column(db.String(100), nullable=False)
    question_type = db.Column(db.String(20), nullable=False, default='Subjective')
    difficulty = db.Column(db.String(20), nullable=False)
    marks = db.Column(db.Integer, nullable=False, default=1)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(250), nullable=True)
    option_b = db.Column(db.String(250), nullable=True)
    option_c = db.Column(db.String(250), nullable=True)
    option_d = db.Column(db.String(250), nullable=True)
    answer_key = db.Column(db.Text, nullable=True)


class Notice(db.Model):
    __tablename__ = 'notices'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    target_class = db.Column(db.String(20), default='All Classes')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OnlineExam(db.Model):
    __tablename__ = 'online_exams'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    target_class = db.Column(db.String(15), nullable=False)
    subject = db.Column(db.String(50), nullable=False)
    chapter = db.Column(db.String(100), nullable=False)
    created_by = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    questions = db.relationship('ExamMCQ', backref='exam', cascade='all, delete-orphan', order_by='ExamMCQ.id.asc()')
    attempts = db.relationship('ExamAttempt', backref='exam', cascade='all, delete-orphan')


class ExamMCQ(db.Model):
    __tablename__ = 'exam_mcqs'
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('online_exams.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(250), nullable=False)
    option_b = db.Column(db.String(250), nullable=False)
    option_c = db.Column(db.String(250), nullable=False)
    option_d = db.Column(db.String(250), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)
    marks = db.Column(db.Integer, default=1)


class ExamAttempt(db.Model):
    __tablename__ = 'exam_attempts'
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey('online_exams.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total_marks = db.Column(db.Integer, nullable=False)
    correct_count = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship('User', backref='exam_attempts')
