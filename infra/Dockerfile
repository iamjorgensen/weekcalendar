# Render Lambda image. Build context = repository root:
#   docker build --platform linux/amd64 -f infra/Dockerfile -t weekcalendar-render .
# BASE_IMAGE can be overridden (e.g. amazon/aws-lambda-python:3.12 from Docker Hub, the same image).
ARG BASE_IMAGE=public.ecr.aws/lambda/python:3.12
FROM ${BASE_IMAGE}

COPY infra/requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements-lambda.txt

# App code (unchanged from the Pi) + the Lambda wrappers
COPY main.py data_provider.py layout_renderer.py mappings.py inky_icons_package.py weather_provider.py ${LAMBDA_TASK_ROOT}/
COPY aws_lambda/aws_common.py aws_lambda/render_handler.py ${LAMBDA_TASK_ROOT}/

# Fonts and bundled icons only (see .dockerignore for what is excluded)
COPY assets/fonts/ ${LAMBDA_TASK_ROOT}/assets/fonts/
COPY assets/icons/ ${LAMBDA_TASK_ROOT}/assets/icons/

CMD ["render_handler.handler"]
