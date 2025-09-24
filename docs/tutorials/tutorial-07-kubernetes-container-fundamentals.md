# Tutorial 7: Kubernetes and Container Fundamentals

## Overview
This tutorial advances the [Sugarkube Tutorial Roadmap](./index.md#tutorial-7-kubernetes-and-container-fundamentals)
by demystifying containers, Kubernetes primitives, and Helm through a guided lab you can complete on
a laptop before touching the Sugarkube cluster. You will create a local Kubernetes sandbox, deploy a
sample workload, customise it with Helm, and practice debugging when pods fail. The exercises focus on
repeatable evidence collection so you build habits that translate directly to Sugarkube operations.

By the end you will have:
* Installed a local Kubernetes toolchain (`docker`, `kind`, `kubectl`, and `helm`).
* Deployed and scaled a containerised web service while recording cluster state.
* Customised a Helm release and documented how configuration changes roll out.
* Practised self-healing concepts by deleting pods and confirming Kubernetes replaces them.

## Prerequisites
* Hardware handling and safety notes from
  [Tutorial 1](./tutorial-01-computing-foundations.md).
* Terminal workflow and documentation habits from
  [Tutorial 2](./tutorial-02-navigating-linux-terminal.md).
* Network vocabulary and diagnostics from
  [Tutorial 3](./tutorial-03-networking-internet-basics.md) to interpret service endpoints.
* Git collaboration workflow from
  [Tutorial 4](./tutorial-04-version-control-collaboration.md) for tracking lab artefacts.
* Automation workspace from
  [Tutorial 5](./tutorial-05-programming-for-operations.md) so you can run scripts and capture logs.
* Assembled Sugarkube hardware from
  [Tutorial 6](./tutorial-06-raspberry-pi-hardware-power.md) (or an equivalent workstation) to run the
  local lab.
* Administrative access to your workstation with virtualisation enabled (BIOS/UEFI setting). If you
  cannot install Docker or Podman, use a cloud VM with at least 2 vCPUs and 4 GB RAM.

> [!WARNING]
> Containers share the host kernel. Only run workloads you trust and keep your operating system
> patched. If you are unsure about your host security posture, consider creating a disposable VM for
> this lab.

## Lab: Launch, Observe, and Heal a Local Kubernetes Cluster
Store all work under `~/sugarkube-tutorials/tutorial-07/`. Create subdirectories named `cluster/`,
`manifests/`, `charts/`, and `reports/` to keep configuration and evidence tidy.

### 1. Prepare your workstation and toolchain
1. Create the lab directory and initialise version control:

   ```bash
   mkdir -p ~/sugarkube-tutorials/tutorial-07/{cluster,manifests,charts,reports}
   cd ~/sugarkube-tutorials/tutorial-07
   git init
   ```

2. Verify container support. On Linux or macOS, check Docker first:

   ```bash
   docker version --format '{{.Server.Version}}'
   ```

   On Windows, run the same command inside PowerShell or WSL. If the command fails, install Docker
   Desktop or refer to the [official Docker Engine guides](https://docs.docker.com/engine/install/).

3. Install `kind` (Kubernetes in Docker) if it is missing:

   ```bash
   curl -Lo kind "https://kind.sigs.k8s.io/dl/v0.22.0/kind-linux-amd64"
   chmod +x kind
   sudo mv kind /usr/local/bin/
   kind --version
   ```

   Replace `linux-amd64` with `darwin-amd64`, `darwin-arm64`, or `windows-amd64.exe` as needed.

4. Install `kubectl` and `helm`:

   ```bash
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
   chmod +x kubectl
   sudo mv kubectl /usr/local/bin/
   kubectl version --client --output=yaml

   curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
   helm version
   ```

5. Record tool versions for auditing:

   ```bash
   {
     echo "# Tutorial 7 Tool Versions"
     date --iso-8601=seconds
     docker --version
     kind --version
     kubectl version --client
     helm version
   } > reports/tool-versions.txt
   git add reports/tool-versions.txt
   git commit -m "Record Kubernetes lab tool versions"
   ```

> [!TIP]
> If corporate policy prevents installing binaries into `/usr/local/bin`, create `~/bin/`, add it to
> your `PATH`, and copy the executables there instead. Document the location in `reports/tool-versions.txt`.

### 2. Create a kind cluster tailored for Sugarkube concepts
1. Write a kind configuration that enables an ingress-ready control plane and exposes a load balancer
   port. Save it as `cluster/kind-config.yaml`:

   ```bash
   cat <<'YAML' > cluster/kind-config.yaml
   kind: Cluster
   apiVersion: kind.x-k8s.io/v1alpha4
   name: sugarkube-lab
   nodes:
     - role: control-plane
       kubeadmConfigPatches:
         - |
           kind: ClusterConfiguration
           metadata:
             name: config
           apiServer:
             extraArgs:
               enable-admission-plugins: "NodeRestriction"
       extraPortMappings:
         - containerPort: 30080
           hostPort: 30080
           protocol: TCP
   networking:
     disableDefaultCNI: false
     kubeProxyMode: "iptables"
   YAML
   ```

2. Create the cluster and capture the logs:

   ```bash
   kind create cluster --config cluster/kind-config.yaml | tee reports/kind-create.log
   ```

3. Point `kubectl` to the new context and verify cluster information:

   ```bash
   kubectl cluster-info > reports/kubectl-cluster-info.txt
   kubectl get nodes -o wide | tee reports/kubectl-nodes.txt
   ```

4. Commit the configuration and baseline evidence:

   ```bash
   git add cluster/kind-config.yaml reports/kind-create.log reports/kubectl-cluster-info.txt \
     reports/kubectl-nodes.txt
   git commit -m "Provision kind cluster and capture baseline evidence"
   ```

> [!NOTE]
> `kind` stores clusters inside Docker. If you ever need to reset, run `kind delete cluster --name
> sugarkube-lab` and rerun this section.

### 3. Deploy and expose a sample web service
1. Create a deployment and service manifest at `manifests/hello-server.yaml`:

   ```bash
   cat <<'YAML' > manifests/hello-server.yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: hello-server
   spec:
     replicas: 1
     selector:
       matchLabels:
         app: hello-server
     template:
       metadata:
         labels:
           app: hello-server
       spec:
         containers:
           - name: web
             image: nginx:1.25-alpine
             ports:
               - containerPort: 80
             readinessProbe:
               httpGet:
                 path: /
                 port: 80
               initialDelaySeconds: 5
               periodSeconds: 10
             livenessProbe:
               httpGet:
                 path: /
                 port: 80
               initialDelaySeconds: 10
               periodSeconds: 20
             resources:
               requests:
                 cpu: 25m
                 memory: 64Mi
               limits:
                 cpu: 100m
                 memory: 128Mi
   ---
   apiVersion: v1
   kind: Service
   metadata:
     name: hello-server
   spec:
     type: NodePort
     selector:
       app: hello-server
     ports:
       - port: 80
         targetPort: 80
         nodePort: 30080
   YAML
   ```

2. Apply the manifest and watch pods start:

   ```bash
   kubectl apply -f manifests/hello-server.yaml | tee reports/kubectl-apply-hello.txt
   kubectl get pods --watch --selector app=hello-server &
   POD_WATCH_PID=$!
   sleep 30
   kill $POD_WATCH_PID
   kubectl get pods -l app=hello-server -o wide > reports/pods-hello-server.txt
   ```

3. Test service reachability from the host:

   ```bash
   curl -vk http://localhost:30080/ | tee reports/hello-service-response.txt
   ```

4. Commit the deployment artefacts:

   ```bash
   git add manifests/hello-server.yaml reports/kubectl-apply-hello.txt \
     reports/pods-hello-server.txt reports/hello-service-response.txt
   git commit -m "Deploy hello-server workload and verify service"
   ```

> [!TROUBLESHOOT]
> If `curl` fails, ensure Docker is forwarding port 30080. Run `docker ps` to confirm the kind control
> plane container exposes `0.0.0.0:30080->30080/tcp`. If not, delete and recreate the cluster after
> verifying `cluster/kind-config.yaml` was saved correctly.

### 4. Scale workloads and observe reconciliation
1. Increase replica count and record the rollout:

   ```bash
   kubectl scale deployment hello-server --replicas=3 | tee reports/kubectl-scale-hello.txt
   kubectl rollout status deployment/hello-server | tee reports/kubectl-rollout-hello.txt
   kubectl get pods -l app=hello-server -o json > reports/pods-hello-server.json
   ```

2. Capture resource usage snapshots:

   ```bash
   kubectl top pods -l app=hello-server --use-protocol-buffers > reports/kubectl-top-hello.txt || \
     echo "metrics-server not available; recorded placeholder" >> reports/kubectl-top-hello.txt
   ```

3. Commit the scaling evidence:

   ```bash
   git add reports/kubectl-scale-hello.txt reports/kubectl-rollout-hello.txt \
     reports/pods-hello-server.json reports/kubectl-top-hello.txt
   git commit -m "Scale hello-server and capture reconciliation data"
   ```

> [!TIP]
> `kubectl top` requires metrics support. If the command reports an error, note it in the file so you
> remember to revisit metrics once the Sugarkube cluster is running.

### 5. Customise a Helm release
1. Add the Bitnami chart repository and update indices:

   ```bash
   helm repo add bitnami https://charts.bitnami.com/bitnami
   helm repo update
   ```

2. Create a values file at `charts/nginx-values.yaml` to enable HTTPS redirects and customise the
   welcome page:

   ```bash
   cat <<'YAML' > charts/nginx-values.yaml
   fullnameOverride: sugarkube-nginx
   service:
     type: ClusterIP
     ports:
       http: 80
       https: 443
   ingress:
     enabled: false
   serverBlock: |-
     server {
       listen 0.0.0.0:8080;
       server_name _;
       location / {
         return 200 'Sugarkube lab nginx running on port $server_port\n';
       }
     }
   YAML
   ```

3. Install the chart into its own namespace and document the release:

   ```bash
   helm upgrade --install sugarkube-web bitnami/nginx \
     --namespace web --create-namespace \
     --values charts/nginx-values.yaml | tee reports/helm-install-sugarkube-web.txt
   kubectl get all -n web > reports/kubectl-get-all-web.txt
   ```

4. Port-forward the service and capture the response:

   ```bash
   kubectl port-forward -n web svc/sugarkube-nginx 8080:80 &
   PF_PID=$!
   sleep 3
   curl -s http://localhost:8080/ | tee reports/nginx-port-forward.txt
   kill $PF_PID
   ```

5. Commit Helm artefacts:

   ```bash
   git add charts/nginx-values.yaml reports/helm-install-sugarkube-web.txt \
     reports/kubectl-get-all-web.txt reports/nginx-port-forward.txt
   git commit -m "Install customised nginx Helm release"
   ```

> [!TROUBLESHOOT]
> If `helm upgrade --install` fails with a timeout, check cluster capacity via `kubectl describe node`
> and free up resources by deleting unused pods. `kind` defaults to modest CPU/RAM limits.

### 6. Practise self-healing and log collection
1. Delete one pod from each workload and observe recovery:

   ```bash
   HELLO_POD=$(kubectl get pods -l app=hello-server -o jsonpath='{.items[0].metadata.name}')
   kubectl delete pod "$HELLO_POD"

   WEB_POD=$(kubectl get pods -n web -l app.kubernetes.io/instance=sugarkube-web -o jsonpath='{.items[0].metadata.name}')
   kubectl delete pod -n web "$WEB_POD"

   kubectl get pods -A > reports/pods-after-deletions.txt
   kubectl describe deployment hello-server > reports/describe-hello-server.txt
   kubectl describe deployment -n web sugarkube-web-nginx > reports/describe-web-deployment.txt
   ```

2. Record the event stream to understand what happened:

   ```bash
   kubectl get events --sort-by='.lastTimestamp' -A | tail -n 40 > reports/events-tail.txt
   ```

3. Commit the incident evidence:

   ```bash
   git add reports/pods-after-deletions.txt reports/describe-hello-server.txt \
     reports/describe-web-deployment.txt reports/events-tail.txt
   git commit -m "Capture self-healing behaviour after pod deletions"
   ```

> [!WARNING]
> Always collect `kubectl describe` and `kubectl get events` output before making additional changes.
> Evidence evaporates quickly in Kubernetes clusters once objects are garbage-collected.

### 7. Clean up and reflect
1. Export a summary report for future reference:

   ```bash
   cat <<'MARKDOWN' > reports/summary.md
   # Tutorial 7 Summary

   ## Cluster
   MARKDOWN

   kubectl config current-context | sed 's/^/- Context: /' >> reports/summary.md
   kubectl get nodes --no-headers | wc -l | sed 's/^/- Nodes: /' >> reports/summary.md

   cat <<'MARKDOWN' >> reports/summary.md

   ## Workloads
   MARKDOWN

   kubectl get deployment hello-server -o jsonpath='{.status.readyReplicas}' \
     | sed 's/^/- hello-server ready replicas: /' >> reports/summary.md
   {
     echo "- web namespace services:"
     kubectl get svc -n web | sed 's/^/  /'
   } >> reports/summary.md

   cat <<'MARKDOWN' >> reports/summary.md

   ## Notes
   MARKDOWN

   date --iso-8601=seconds | sed 's/^/- Lab completed at: /' >> reports/summary.md
   ```

   Review `reports/summary.md` and add bullet points describing what surprised you and any
   troubleshooting you performed.

2. Tag the lab state:

   ```bash
   git add reports/summary.md
   git commit -m "Draft tutorial 7 lab summary"
   git tag -a tutorial-07-complete -m "Completed Kubernetes fundamentals lab"
   ```

3. When ready to reclaim resources, delete the cluster:

   ```bash
   kind delete cluster --name sugarkube-lab | tee reports/kind-delete.log
   git add reports/kind-delete.log
   git commit -m "Tear down kind cluster after lab"
   ```

## Milestone Checklist
Use this checklist to confirm you met the roadmap milestones. Mark each item complete in your lab
repository README or tracking spreadsheet.

### Milestone 1: Launch a local Kubernetes cluster and deploy a sample app
- [ ] Saved `cluster/kind-config.yaml` and `reports/kind-create.log` showing a successful `kind` build.
- [ ] Captured `reports/kubectl-cluster-info.txt` and `reports/kubectl-nodes.txt` with node details.
- [ ] Applied `manifests/hello-server.yaml` and recorded the service response in `reports/hello-service-response.txt`.

### Milestone 2: Customise a Helm release and record resource usage
- [ ] Stored Helm values at `charts/nginx-values.yaml` and the install log at `reports/helm-install-sugarkube-web.txt`.
- [ ] Documented workload state with `reports/kubectl-get-all-web.txt` and `reports/nginx-port-forward.txt`.
- [ ] Logged scaling activity in `reports/kubectl-scale-hello.txt`, `reports/kubectl-rollout-hello.txt`, and resource snapshots in `reports/kubectl-top-hello.txt`.

### Milestone 3: Validate self-healing and observe reconciliation loops
- [ ] Archived deletion evidence with `reports/pods-after-deletions.txt` and deployment descriptions.
- [ ] Captured the event stream in `reports/events-tail.txt`.
- [ ] Summarised the incident response in `reports/summary.md`.

## Next Steps
Advance to [Tutorial 8: Preparing a Sugarkube Development Environment](./index.md#tutorial-8-preparing-a-sugarkube-development-environment)
when it becomes available. That guide will translate your Kubernetes sandbox experience into the
exact automation workflow used inside the Sugarkube repository.
