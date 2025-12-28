import smtplib
from email.message import EmailMessage
import os

smtp_host = "smtp.gmail.com"
smtp_port = 587
smtp_user = "gondgesagar.2025@gmail.com"
smtp_pass = input("Enter SMTP password: ")
email_from = "gondgesagar@gmail.com"
email_to = "gondgesagar.2025@gmail.com"

msg = EmailMessage()
msg["Subject"] = "Test Email"
msg["From"] = email_from
msg["To"] = email_to
msg.set_content("This is a test email.")

try:
    with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
    print("Email sent successfully!")
except Exception as e:
    print(f"Error: {e}")