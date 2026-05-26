import os
from flask import Flask
from dotenv import load_dotenv
from database.extensions import db
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from utils.hpc.hpc_notify_utils import check_hpc_usage_and_notify
from server_route import mailbox_bp, hpc_bp, email_bp, template_bp, routes_bp, contact_bp, quota_bp

app = Flask(__name__)

# 配置資料庫
load_dotenv()
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URI', 'sqlite:///hpc.db')
db.init_app(app)

app.register_blueprint(mailbox_bp)
app.register_blueprint(hpc_bp)
app.register_blueprint(email_bp)
app.register_blueprint(template_bp)
app.register_blueprint(routes_bp)
app.register_blueprint(contact_bp)
app.register_blueprint(quota_bp)



def check_hpc_usage_in_context():
    with app.app_context():
        check_hpc_usage_and_notify()



# --- run server ---
if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    # scheduler.add_job(
    #     func=check_hpc_usage_in_context,
    #     trigger="interval",
    #     days=load_hpc_settings()['check_interval'],
    #     id='hpc_check_job'
    # )
    # scheduler.add_job(
    # func=check_hpc_usage_in_context,
    # trigger='date',
    # run_date=datetime.now() + timedelta(seconds=5),
    # id='one_time_hpc_check'
    # )
    # scheduler.start()
    app.run(debug=True, use_reloader=False)