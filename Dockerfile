FROM ubuntu:focal

RUN apt update && DEBIAN_FRONTEND=noninteractive apt install -y python3 python3-pip imagemagick libttspico-utils ffmpeg
VOLUME /lunii-podcast
WORKDIR /lunii-podcast
COPY ./requirements.txt /lunii-podcast
RUN pip install -r requirements.txt

