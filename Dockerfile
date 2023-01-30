FROM python:3.10.9-alpine
LABEL maintainer="Adam Carlin"
RUN pip install requests==2.28.2 httpx==0.23.3 slack-sdk==3.19.5
ADD monitor_dc_temp.py ./app/monitor_dc_temp.py
WORKDIR ./app
CMD python3 /app/monitor_dc_temp.py -v -f