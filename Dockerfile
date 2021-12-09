FROM python:3.8-slim

WORKDIR /opt/riki

RUN apt-get update
RUN apt-get -y install build-essential mercurial

RUN pip3 install --upgrade pip


COPY ./requirements.txt /opt/riki/requirements.txt
RUN pip3 install -r /opt/riki/requirements.txt
RUN mkdir /var/opt/riki
RUN mkdir /var/opt/riki/data
RUN mkdir /var/opt/riki/tpl
RUN mkdir /var/opt/riki/pic-cache
RUN mkdir /var/log/riki
RUN touch /var/log/riki/riki.log

#COPY static static
#COPY templates templates
#COPY app.py config.json files.py index.py ./

CMD ["python3", "./app.py"]