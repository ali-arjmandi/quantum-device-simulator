.PHONY: run install test

run:
	FLASK_APP=app flask run

create-requirements:
	pip freeze > requirements.txt
