FROM python:3.8-slim

RUN apt-get update
RUN apt-get -y install build-essential

RUN pip3 install --upgrade pip
RUN pip3 install jinja2 web.py dataclasses-json Whoosh Pillow markdown mercurial


RUN mkdir /opt/riki
RUN mkdir /var/opt/riki
RUN mkdir /var/opt/riki/data
RUN mkdir /var/opt/riki/tpl
RUN mkdir /var/opt/riki/pic-cache
RUN mkdir /var/log/riki
RUN touch /var/log/riki/riki.log

WORKDIR /opt/riki

#COPY static static
#COPY templates templates
#COPY app.py config.json files.py index.py ./

CMD ["python3", "./app.py"]