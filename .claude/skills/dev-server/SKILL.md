# Dev Server Skill

Start the Flask dev server for this project using the correct venv and an available port.

## Steps

1. Activate the project venv at `.venv` — never use system Python.
2. Scan ports 5002–5010 with `lsof -i :<port>` and pick the first free one.
3. Set `FLASK_APP=web/app.py` and `FLASK_ENV=development`, then start the server on the chosen port in the background, writing output to `/tmp/flask-dev.log`.
4. Tail `/tmp/flask-dev.log` for 5 seconds so startup errors are visible.
5. Curl `http://localhost:<port>/` and confirm a 2xx response; print the port and PID on success.

## Example invocation

```bash
# Find a free port
for port in 5002 5003 5004 5005 5006 5007 5008 5009 5010; do
  lsof -i :$port &>/dev/null || { FREE_PORT=$port; break; }
done

# Start the server
source .venv/bin/activate
FLASK_APP=web/app.py FLASK_ENV=development python3 -m flask run --port $FREE_PORT > /tmp/flask-dev.log 2>&1 &
FLASK_PID=$!

# Tail logs briefly
sleep 3 && tail -20 /tmp/flask-dev.log

# Health check
curl -s -o /dev/null -w "%{http_code}" http://localhost:$FREE_PORT/
echo "Server running on port $FREE_PORT (PID $FLASK_PID)"
```

## Teardown

```bash
kill $FLASK_PID   # or: pkill -f "flask run"
```
