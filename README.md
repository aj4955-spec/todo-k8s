# todo-k8s

CS-GY 9223 Cloud Computing and Big Data Systems, Fall 2026, Assignment 2.
A Flask and MongoDB To Do app, containerized with Docker, run with Docker Compose,
deployed on Minikube and AWS EKS, with health probes, rolling updates, and
Prometheus alerts sent to Slack.

Team: Aditya Jha (aj4955), Pragya Awasthi (pa2755)

The full write-up, with screenshots and every command used, is in
[`docs/Cloud_Assignment_2_Report.pdf`](docs/Cloud_Assignment_2_Report.pdf).

## Repository layout

| Path | Contents |
| --- | --- |
| `app/` | Flask app, `Dockerfile`, `.dockerignore`, `requirements.txt` |
| `docker-compose.yml`, `.env.example` | Local run with Flask and MongoDB containers and a named volume |
| `k8s/base/` | Namespace, ConfigMap, Secret template, MongoDB PVC, Deployment and Service, app Deployment and Service, Kustomize base |
| `k8s/overlays/minikube/` | Exposes the app Service as NodePort 30080 |
| `k8s/overlays/eks/` | Exposes the app Service as a LoadBalancer and stores MongoDB data on a gp3 EBS volume |
| `eks/` | eksctl cluster config and EBS CSI driver add-on |
| `monitoring/` | Helm values, ServiceMonitor, alert rules, Alertmanager routing to Slack |
| `docs/` | Report |

## Image

`thisisadityajha/todo-flask` on Docker Hub, built for `linux/amd64` and `linux/arm64`.

| Tag | Contents |
| --- | --- |
| `v1` | First release |
| `v2` | Same code, `APP_VERSION=v2`; target of the rolling update |
| `v3-broken` | Imports a missing module and crashes on start; used for failure tests |

## Run with Docker Compose

```bash
cp .env.example .env            # set MONGO_USER and MONGO_PASSWORD (letters and digits only)
docker compose up -d --build
open http://localhost:8080      # host port 8080, because macOS uses 5000 for AirPlay
docker compose down             # add -v to also delete the data volume
```

## Deploy on Minikube

```bash
minikube start --driver=docker --cpus=4 --memory=8192
kubectl apply -f k8s/base/namespace.yaml
kubectl create secret generic mongo-credentials -n todo \
  --from-literal=MONGO_USER=<user> --from-literal=MONGO_PASSWORD=<password>
kubectl apply -k k8s/overlays/minikube
minikube service todo-app -n todo --url
```

## Deploy on AWS EKS

```bash
eksctl create cluster -f eks/cluster.yaml
aws eks update-kubeconfig --name todo-eks --region us-east-1
eksctl create addon -f eks/addon-ebs.yaml
kubectl apply -f k8s/base/namespace.yaml
kubectl create secret generic mongo-credentials -n todo \
  --from-literal=MONGO_USER=<user> --from-literal=MONGO_PASSWORD=<password>
kubectl apply -k k8s/overlays/eks
kubectl -n todo get svc todo-app        # EXTERNAL-IP is the load balancer address
```

Tear down in this order so the load balancer and EBS volume are removed too:

```bash
kubectl delete -k k8s/overlays/eks
eksctl delete cluster -f eks/cluster.yaml --wait
```

The node group uses `m7i-flex.large` because AWS free plan accounts can only launch
free tier eligible instance types.

## Monitoring and Slack alerts

```bash
kubectl create namespace monitoring
kubectl create secret generic alertmanager-slack -n monitoring --from-literal=url="$SLACK_WEBHOOK_URL"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm upgrade --install mon prometheus-community/kube-prometheus-stack -n monitoring \
  -f monitoring/values.yaml -f monitoring/alertmanager-slack.yaml
kubectl apply -f monitoring/todo-servicemonitor.yaml -f monitoring/todo-alert-rules.yaml
```

Always pass both values files to `helm upgrade`; leaving one out resets its settings.
Only alerts labelled `team: todo` reach Slack, and `TodoMongoDown` suppresses the
readiness alerts it causes.

## App configuration

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
| `GET /healthz` | Liveness: 200, or 500 if `/tmp/unhealthy` exists. Never touches the database. |
| `GET /readyz` | Readiness: 200 if MongoDB answers a ping, 503 otherwise (within about 2 seconds). |
| `GET /version` | JSON with the app version and pod name. |
| `GET /metrics` | Prometheus metrics. Probe endpoints are excluded. |
| `POST /chaos/fail-liveness` | Creates `/tmp/unhealthy` so liveness fails. Only when `ENABLE_CHAOS=true`, otherwise 404. |
| `POST /chaos/recover` | Removes the flag. Only when `ENABLE_CHAOS=true`, otherwise 404. |

## Error handling

| Situation | Response |
| --- | --- |
| MongoDB unreachable | Friendly 503 page after about 2 seconds |
| Invalid task id | 400 |
| Valid id that does not exist | 404 |
| Empty task name | 400 |
| Search on an unknown field | 400 |
| Search text with special characters | Treated as plain text |
| Wrong HTTP method or unknown page | Friendly 405 or 404 page |

## Secrets

Credentials never go in Git. `.env` is gitignored, the MongoDB password is created
with `kubectl create secret`, and the Slack webhook lives only in the
`alertmanager-slack` Secret, which `monitoring/alertmanager-slack.yaml` references
by file path.
