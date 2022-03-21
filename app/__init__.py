import logging.config
from os import environ
from celery import Celery
from dotenv import load_dotenv
from flask import Flask, redirect, request
from flask_login import LoginManager
from .extensions import cache
from flask_cors import CORS
celery = Celery(__name__)

from .config import config as app_config
from .dl.dl import media_path
from .serve.db import db_session, init_db, load_all_videos_from_disk, User


def create_app():
    # loading env vars from .env file
    load_dotenv()
    APPLICATION_ENV = get_environment()
    logging.config.dictConfig(app_config[APPLICATION_ENV].LOGGING)
    app = Flask(app_config[APPLICATION_ENV].APP_NAME)
    app.config.from_object(app_config[APPLICATION_ENV])
    app.config["SECRET_KEY"] = app_config[APPLICATION_ENV].SECRET_KEY

    log = app.logger
    log.info("Loading LoginManager")
    login_manager = LoginManager()
    login_manager.login_view = "serve.login_page"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    log.info("Loading CORS")
    CORS(app, resources={r'/api/*': {'origins': '*'}})

    log.info("Loading celery")
    celery.config_from_object(app.config, force=True)
    # celery is not able to pick result_backend and hence using update
    celery.conf.update(result_backend=app.config['RESULT_BACKEND'])

    log.info("Registering blueprints")
    from .core.views import core as core_blueprint
    app.register_blueprint(
        core_blueprint,
        url_prefix='/api/v1/core'
    )
    from .serve.views import serve as serve_blueprint
    app.register_blueprint(
        serve_blueprint
    )
    cache.init_app(app)

    @app.errorhandler(404)
    def page_not_found(_e):
        return redirect("https://" if request.is_secure else "http://" + app.config["SERVER_NAME"])

    # log.info("Loading videos from disk")
    # with app.app_context():
    #     load_all_videos_from_disk(media_path)

    log.info("Starting app")
    return app


def get_environment():
    return environ.get('APPLICATION_ENV') or 'development'
