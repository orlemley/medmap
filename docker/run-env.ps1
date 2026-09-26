docker run --rm -it \
  -p 5173:5173 \
  -v "$(pwd)/web:/app" \
  -v /app/node_modules \
  node:20-slim