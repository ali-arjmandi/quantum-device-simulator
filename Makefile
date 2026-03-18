.PHONY: run install test docker-run gunicorn

run:
	FLASK_APP=app FLASK_RUN_PORT=5555 flask run

docker-run:
	docker compose up --build

gunicorn:
	gunicorn -k gthread -w 1 --threads 8 -b 0.0.0.0:5555 --timeout 120 app:app

create-requirements:
	pip freeze > requirements.txt
