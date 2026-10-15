FROM public.ecr.aws/lambda/python:3.14@sha256:486b444fbc2079290e331eb86c4e1a5f11eb72873bd2ea883b177a1cd070ed09
RUN pip install --no-cache-dir uv==0.12.23
COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY_NOTICES.md /tmp/project/
RUN cd /tmp/project && uv export --frozen --no-dev --no-emit-project -o /tmp/requirements.txt > /dev/null \
    && uv pip install --system --require-hashes -r /tmp/requirements.txt
COPY dist/*.whl /tmp/wheels/
RUN uv pip install --system --no-deps /tmp/wheels/*.whl
COPY web/ ${LAMBDA_TASK_ROOT}/web/
COPY examples/playground/lessons.json examples/playground/demand-adjustment.json examples/playground/consecutive-days.json examples/playground/manual-verify.json examples/playground/manual-verify.solution.json ${LAMBDA_TASK_ROOT}/examples/playground/
CMD ["web.handler.lambda_handler"]
