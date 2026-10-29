# todo-k8s

Cloud Computing and Big Data Systems (CS-GY 9223), Fall 2026, Assignment 2.
Flask + MongoDB To Do app on Docker, Compose, Minikube and AWS EKS, with probes,
rolling updates, and Prometheus to Slack alerting.

Team: Aditya Jha, Pragya Awasthi

## Shared contract (frozen, do not rename without telling the other person)

| Item | Value |
|---|---|
| Image | `thisisadityajha/todo-flask` |
| Tags | `v1` baseline, `v2` visible change, `v3-broken` crashes on start. Never deploy `latest`. Never overwrite a pushed tag. |
| App port | 5000 inside the container |
| Service port | 80 (NodePort 30080 on Minikube, LoadBalancer on EKS) |
| Namespace | `todo` |
| Labels | `app: todo-app` (Flask), `app: mongo` (MongoDB), both with `part-of: todo` |
| App env vars | `MONGO_URI`, `MONGO_DB` (default `todo_db`), `APP_VERSION`, `ENABLE_CHAOS`, `LOG_LEVEL` |
| Mongo env vars | `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD` from Secret `mongo-credentials` |
| Endpoints | `/healthz` liveness, `/readyz` readiness, `/version`, `/metrics`, `POST /chaos/fail-liveness`, `POST /chaos/recover` |
| Mongo image | `mongo:7.0` (fallback `mongo:4.4` if the CPU lacks AVX) |
| Mongo service | `mongo`, port 27017 |
| Branches | `pragya/<topic>`, `aditya/<topic>`, merge to `main` by reviewed PR |
| AWS | account 466558794910, region `us-east-1` |
| Slack | workspace `cloud-a2-todo`, private channel `#k8s-alerts` |

## Repo layout

| Folder | Contents |
|---|---|
| `app/` | Flask app, Dockerfile, .dockerignore, requirements.txt |
| `k8s/base/` | Namespace, ConfigMap, Mongo PVC, Deployment and Service, app Deployment and Service |
| `k8s/overlays/` | `minikube` (NodePort) and `eks` (LoadBalancer, gp3) |
| `k8s/optional/` | ReplicationController example |
| `eks/` | eksctl cluster config |
| `monitoring/` | Helm values, ServiceMonitor, PrometheusRule, Alertmanager config |
| `scripts/chaos/` | Failure test helpers |
| `docs/` | Report and screenshots |

## Secrets

Never commit `.env`, `mongo-secret.yaml`, `alertmanager-slack.yaml`, tokens or webhook URLs.
Use letters and digits only for the Mongo password.

## Endpoints

(Filled in by Pragya in P1.)

## Runbook

(Each owner adds the commands for their part.)
## Run locally

```bash
docker run -d --name todo-mongo -p 27017:27017 mongo:7.0
python3 -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt
cd app && FLASK_APP=app python -m flask run --port 5001
```

Port 5001 is used because macOS AirPlay Receiver occupies port 5000.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB` | `todo_db` | Database name |
| `APP_VERSION` | `dev` | Shown in the page footer and `/version` |
| `ENABLE_CHAOS` | `false` | Enables the chaos endpoints below |
| `LOG_LEVEL` | `INFO` | Python logging level |

## Endpoints added for Kubernetes

| Endpoint | Returns |
| --- | --- |
| `GET /healthz` | Liveness. 200 if the process is fine, 500 if `/tmp/unhealthy` exists. Never touches the database. |
| `GET /readyz` | Readiness. 200 if MongoDB answers a ping, 503 otherwise (within about 2 seconds). |
| `GET /version` | JSON with the app version and pod name. |
| `POST /chaos/fail-liveness` | Creates `/tmp/unhealthy` so liveness starts failing. Only when `ENABLE_CHAOS=true`, else 404. |
| `POST /chaos/recover` | Removes the flag. Only when `ENABLE_CHAOS=true`, else 404. |
| `GET /metrics` | Prometheus metrics (request counts and latencies). Probe endpoints are excluded. |

## Error handling

| Situation | Response |
| --- | --- |
| MongoDB unreachable | 503 friendly page after about 2 seconds (no 30 second hang) |
| Invalid task id in a URL | 400 |
| Valid id that doesn't exist | 404 |
| Empty task name | 400 |
| Search on an unknown field | 400 |
| Search text with special characters | Treated as plain text (escaped) |
| Wrong HTTP method or unknown page | 405 or 404 friendly page |
