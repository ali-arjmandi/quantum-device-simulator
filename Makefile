.PHONY: run install test docker-run gunicorn

run:
	FLASK_APP=app FLASK_RUN_PORT=5555 flask run

docker-run:
	docker compose up --build

gunicorn:
	gunicorn -b 0.0.0.0:5555 app:app

create-requirements:
	pip freeze > requirements.txt
