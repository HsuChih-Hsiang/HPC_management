# utils/session_interface.py
from flask import Flask, request
from flask.sessions import SecureCookieSessionInterface

class CustomSessionInterface(SecureCookieSessionInterface):
    def should_set_cookie(self, app: Flask, session) -> bool:
        if request.endpoint and 'check_session' in request.endpoint:
            return session.modified
        
        return super().should_set_cookie(app, session)