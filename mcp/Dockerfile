# Home Server MCP — read-only MCP server (see server.py)
FROM python:3.12-slim

RUN useradd --uid 1000 --user-group --no-create-home mcp

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .

USER mcp
EXPOSE 8000
CMD ["python", "server.py"]
