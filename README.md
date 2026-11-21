# Flourish Forge Educational Portal (CBSE Classes 7-12)
Director: Shivam Tiwari | B.Sc. (Hons.) Computer Science, University of Delhi

## Quick Start (Local or Render)
1. Install dependencies: `pip install -r requirements.txt`
2. Run locally: `python app.py` (opens at `http://127.0.0.1:5000`)
3. For Render Web Service:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Optional Environment Variables:
     - `ADMIN_EMAIL` (default: `director@flourishforge.in`)
     - `ADMIN_PASSWORD` (default: `flourishforge123`)
     - `MAIL_USERNAME` & `MAIL_PASSWORD` (for real SMTP OTP emails; without them OTP also displays cleanly on screen for instant testing)
