# Home Server MCP — read-only MCP server (see server.py)
# Pinned patch release (Diun skips this locally built image — bump by hand)
FROM python:3.12.16-slim

RUN useradd --uid 1000 --user-group --no-create-home mcp

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./

USER mcp
EXPOSE 8000
CMD ["python", "server.py"]
