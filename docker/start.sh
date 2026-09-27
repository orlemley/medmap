#!/bin/sh
set -e

# install node deps for the react app (kept out of the image build since /app is volume-mounted)
npm --prefix ./app install

# uncomment if server.py has its own dependencies (flask, etc.)
# pip3 install -r ./api/requirements.txt

# start the python api in the background
python3 ./api/server.py &

# start the vite dev server in the foreground — this keeps the container alive
npm --prefix ./app run dev -- --host 0.0.0.0