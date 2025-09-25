# Tutorial 13: Advanced Operations and Future Directions

## Overview
This capstone guide in the
[Sugarkube Tutorial Roadmap](./index.md#tutorial-13-advanced-operations-and-future-directions)
shows you how to extend your cluster beyond the single-node lab you have today. You will pilot a
multi-node expansion, integrate external storage, and exercise an edge AI workload while measuring
performance and resilience. Along the way you will document every experiment so future
collaborators can replay your results or build on them.

By the end you will have:
* Captured a reproducible playbook for adding worker nodes and validating their health under load.
* Provisioned shared storage that survives node failures and published benchmarks that explain your
  design trade-offs.
* Deployed and tuned an AI-powered service, measuring resource impact and recording mitigation
  strategies.

## Prerequisites
* Completed artefacts from [Tutorial 1](./tutorial-01-computing-foundations.md) through
  [Tutorial 12](./tutorial-12-contributing-new-features-automation.md), including your automation
  toolkit, maintenance runbooks, and contribution workflow.
* At least two additional Raspberry Pis (or equivalent ARM/AMD64 nodes) with power supplies, storage
  media, and network connectivity prepared using
  [Tutorial 6](./tutorial-06-raspberry-pi-hardware-power.md) and
  [Tutorial 9](./tutorial-09-building-flashing-pi-image.md).
* A powered Ethernet switch or mesh Wi-Fi backhaul with VLAN support so you can segment lab traffic.
* Optional but recommended: a USB-attached SSD array or NAS that exposes NFS, iSCSI, or SMB shares
  for storage experiments.

> [!WARNING]
> Before expanding the cluster, confirm your power budget. Add up the amperage draw of the
> controller, new nodes, networking gear, and storage. If the total exceeds 80% of the rated output
> for your power strip or UPS, source a higher-capacity supply before proceeding.

Create a workspace for the tutorial and consistent subdirectories for each experiment so artefacts
do not mix with earlier labs:

```bash
mkdir -p ~/sugarkube-labs/tutorial-13/{baseline,expansion,storage,edge-ai,operations,final}
```

Store all notes, command transcripts, and screenshots under `~/sugarkube-labs/tutorial-13/` so you
can reference them while writing future proposals.

## Lab: Expand, Observe, and Optimise Sugarkube

### 1. Validate the baseline cluster
1. SSH into the existing controller node:

   ```bash
   ssh pi@controller.sugarkube.lan
   ```

2. Record the current node list and workloads:

   ```bash
   kubectl get nodes -o wide | tee ~/sugarkube-labs/tutorial-13/baseline/cluster-inventory.txt
   kubectl get pods -A -o wide | tee -a ~/sugarkube-labs/tutorial-13/baseline/cluster-inventory.txt
   ```

   Save the output to `baseline/cluster-inventory.txt` in your lab directory.

3. Capture current resource utilisation using `kubectl top` (requires metrics-server):

   ```bash
   kubectl top nodes | tee ~/sugarkube-labs/tutorial-13/baseline/resource-snapshot.csv
   kubectl top pods -A | tee -a ~/sugarkube-labs/tutorial-13/baseline/resource-snapshot.csv
   ```

   Export the results to `baseline/resource-snapshot.csv` so you can compare post-expansion metrics.

> [!TIP]
> If `kubectl top` fails, install metrics-server from the upstream release manifests:
>
> ```bash
> kubectl apply -f \
>   https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
> ```
>
> Wait until `kubectl get deployment metrics-server -n kube-system` shows `AVAILABLE` replicas
> before retrying.

### 2. Join new worker nodes
1. Image each new Pi using the artefacts from Tutorial 9. Set a unique hostname (for example
   `worker-a` and `worker-b`) by editing `/boot/user-data` before first boot.
2. Boot one node at a time while connected to the same management network as the controller. Confirm
   you can SSH in using the default credentials established in Tutorial 10.
3. On the controller, print the join credential (the command output is sensitive—store it securely).

   ```bash
   sudo k3s token create --print
   ```

   Archive the resulting value in your credential vault and note it privately—never include it in
   commits or screenshots.

4. On each new node, install the k3s agent:

   ```bash
   read -rsp "Paste join credential: " JOIN_CREDENTIAL && echo
   sudo install -d -m 700 /etc/rancher/k3s
   printf '%s' "$JOIN_CREDENTIAL" | sudo tee /etc/rancher/k3s/join-credential >/dev/null
   unset JOIN_CREDENTIAL
   curl -sfL https://get.k3s.io | sudo \
     K3S_URL="https://controller.sugarkube.lan:6443" \
     K3S_TOKEN_FILE="/etc/rancher/k3s/join-credential" \
     INSTALL_K3S_EXEC="--node-taint sugarkube.io/role=worker:NoSchedule" \
     sh -
   ```

   Replace `<paste-token-here>` with the token you generated. The taint keeps critical control-plane
   workloads pinned to the controller until you deliberately schedule them elsewhere.

5. Verify each node registers:

   ```bash
   watch -n5 kubectl get nodes -o wide
   ```

   Once all nodes show `Ready`, stop the watch with `Ctrl+C` and export the node list to
   `expansion/nodes-after-join.txt`.

> [!IMPORTANT]
> If a node sticks in `NotReady`, inspect `/var/log/syslog` and
> `/var/lib/rancher/k3s/agent/containerd/containerd.log` on the worker. Common causes include
> incorrect time synchronisation (fix with `sudo timedatectl set-ntp true`) or firewall rules
> port 6443/TCP.

### 3. Deploy a workload that exercises the cluster
1. Create a namespace for experiments:

   ```bash
   kubectl create namespace lab-scale
   ```

2. Create a load-generator job that runs four parallel `stress-ng` workers for five minutes. Keep
   manifests under your lab workspace so you can version them later:

   ```bash
   mkdir -p ~/sugarkube-labs/tutorial-13/workloads/lab-scale
   cat <<'EOF' > \
     ~/sugarkube-labs/tutorial-13/workloads/lab-scale/stress-load-job.yaml
   apiVersion: batch/v1
   kind: Job
   metadata:
     name: stress-load
     namespace: lab-scale
   spec:
     parallelism: 4
     completions: 4
     template:
       metadata:
         labels:
           app: stress-load
       spec:
         restartPolicy: Never
         containers:
           - name: stress
             image: ghcr.io/alpine/stress:1.0.4
             args:
               - "--cpu"
               - "2"
               - "--io"
               - "2"
               - "--vm"
               - "1"
               - "--vm-bytes"
               - "256M"
               - "--timeout"
               - "5m"
   EOF
   kubectl apply -f \
     ~/sugarkube-labs/tutorial-13/workloads/lab-scale/stress-load-job.yaml
   ```

3. Monitor pod placement to confirm workloads spread across nodes:

   ```bash
   watch -n5 kubectl get pods -n lab-scale -o wide
   ```

   Capture screenshots or pipe the watch output to
   `~/sugarkube-labs/tutorial-13/expansion/pod-distribution.txt`.

4. When the job completes, gather metrics:

   ```bash
   kubectl logs job/stress-load -n lab-scale > \
     ~/sugarkube-labs/tutorial-13/expansion/stress-load-report.log
   ```

   Compare the runtime and resource usage against your baseline snapshot.

### 4. Integrate external storage
1. Decide on the storage backend. For a NAS that exposes NFS, create a `StorageClass` definition
   under `storage/nfs-storageclass.yaml`:

   ```yaml
   apiVersion: storage.k8s.io/v1
   kind: StorageClass
   metadata:
     name: nfs-shared
   provisioner: cluster.local/nfs
   reclaimPolicy: Retain
   mountOptions:
     - vers=4.1
   parameters:
     server: 192.168.42.50
     path: /export/sugarkube
   ```

   Adjust the server IP and path to match your NAS.

   ```bash
   mkdir -p ~/sugarkube-labs/tutorial-13/storage
   cat <<'EOF' > ~/sugarkube-labs/tutorial-13/storage/nfs-storageclass.yaml
   apiVersion: storage.k8s.io/v1
   kind: StorageClass
   metadata:
     name: nfs-shared
   provisioner: cluster.local/nfs
   reclaimPolicy: Retain
   mountOptions:
     - vers=4.1
   parameters:
     server: 192.168.42.50
     path: /export/sugarkube
   EOF
   ```

2. Apply the manifest and confirm the class exists:

   ```bash
   kubectl apply -f ~/sugarkube-labs/tutorial-13/storage/nfs-storageclass.yaml
   kubectl get storageclass
   ```

3. Deploy a sample StatefulSet to validate durability:

   ```bash
   cat <<'EOF' > ~/sugarkube-labs/tutorial-13/storage/statefulset-sqlite.yaml
   apiVersion: apps/v1
   kind: StatefulSet
   metadata:
     name: nfs-sqlite
     namespace: lab-scale
   spec:
     serviceName: nfs-sqlite
     selector:
       matchLabels:
         app: nfs-sqlite
     template:
       metadata:
         labels:
           app: nfs-sqlite
       spec:
         containers:
           - name: sqlite
             image: docker.io/library/busybox:1.36
             command:
               - "/bin/sh"
               - "-c"
               - |
                 set -euo pipefail
                 apk add --no-cache sqlite
                 while true; do
                   sqlite3 /data/measurements.db "CREATE TABLE IF NOT EXISTS metrics(ts TEXT, note TEXT);"
                   sqlite3 /data/measurements.db "INSERT INTO metrics VALUES(datetime('now'), 'nfs smoke test');"
                   sleep 30
                 done
             volumeMounts:
               - name: data
                 mountPath: /data
     volumeClaimTemplates:
       - metadata:
           name: data
         spec:
           accessModes:
             - ReadWriteMany
           resources:
             requests:
               storage: 1Gi
           storageClassName: nfs-shared
   EOF
   kubectl apply -f ~/sugarkube-labs/tutorial-13/storage/statefulset-sqlite.yaml
   kubectl rollout status statefulset/nfs-sqlite -n lab-scale
   ```

   The manifest should mount a `PersistentVolumeClaim` using the `nfs-shared` class and write sample
   data.

4. Simulate a node failure:

   ```bash
   kubectl delete pod nfs-sqlite-0 -n lab-scale
   watch -n5 kubectl get pods -n lab-scale -o wide
   ```

   Confirm Kubernetes reschedules the pod on another node and that the PVC reattaches with data
   intact. Document the observation in `~/sugarkube-labs/tutorial-13/storage/failover-report.md`.

> [!NOTE]
> If the PVC enters `Pending`, ensure the NFS export allows the worker node IPs and that the
> firewall exposes TCP/2049. Run `showmount -e <server>` from each node to verify connectivity.

### 5. Launch an edge AI workload
1. Create a dedicated namespace:

   ```bash
   kubectl create namespace edge-ai
   ```

2. Build a self-contained inference service using FastAPI and ONNX Runtime. The deployment installs
   dependencies on startup, downloads a small sample model, and exposes an `/infer` endpoint.

   ```bash
   mkdir -p ~/sugarkube-labs/tutorial-13/workloads/edge-ai
   cat <<'EOF' > ~/sugarkube-labs/tutorial-13/workloads/edge-ai/inference-app.py
   import io
   import os
   import tempfile
   import urllib.request

   import numpy as np
   from fastapi import FastAPI, File, UploadFile
   from PIL import Image
   import uvicorn
   import onnxruntime as ort

   MODEL_URL = (
       "https://github.com/onnx/models/raw/main/vision/classification/resnet/model/"
       "resnet50-v2-7.onnx"
   )
   MODEL_PATH = os.environ.get("MODEL_PATH", "/models/resnet50.onnx")

   app = FastAPI(title="Sugarkube Edge AI Demo")


   def ensure_model():
       if not os.path.exists(MODEL_PATH):
           os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
           with tempfile.NamedTemporaryFile(delete=False) as tmp:
               urllib.request.urlretrieve(MODEL_URL, tmp.name)
               os.replace(tmp.name, MODEL_PATH)


   def prepare_image(data: bytes) -> np.ndarray:
       img = Image.open(io.BytesIO(data)).convert("RGB").resize((224, 224))
       arr = np.array(img).astype("float32")
       arr = np.transpose(arr, (2, 0, 1))
       arr = np.expand_dims(arr, axis=0) / 255.0
       return arr


   @app.on_event("startup")
   def load_model():
       ensure_model()
       app.session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])


   @app.post("/infer")
   async def infer(image: UploadFile = File(...)):
       data = await image.read()
       tensor = prepare_image(data)
       outputs = app.session.run(None, {app.session.get_inputs()[0].name: tensor})
       scores = outputs[0][0]
       top_idx = int(np.argmax(scores))
       confidence = float(scores[top_idx])
       return {"class_index": top_idx, "confidence": confidence}


   if __name__ == "__main__":
       ensure_model()
       uvicorn.run(app, host="0.0.0.0", port=9000)
   EOF
   ```

   Render a ConfigMap manifest from the script so Kubernetes can mount it into a pod:

   ```bash
   kubectl create configmap vehicle-detector-code -n edge-ai \
     --from-file=inference-app.py=~/sugarkube-labs/tutorial-13/workloads/edge-ai/inference-app.py \
     --dry-run=client -o yaml > \
     ~/sugarkube-labs/tutorial-13/workloads/edge-ai/vehicle-detector-configmap.yaml
   ```

   Create a Kubernetes manifest that mounts the script into a `python:3.11-slim` container, installs
   dependencies, and exposes the service:

   ```bash
   cat <<'EOF' > ~/sugarkube-labs/tutorial-13/workloads/edge-ai/edge-ai-deployment.yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: vehicle-detector
     namespace: edge-ai
   spec:
     replicas: 2
     selector:
       matchLabels:
         app: vehicle-detector
     template:
       metadata:
         labels:
           app: vehicle-detector
       spec:
         containers:
           - name: inference
             image: python:3.11-slim
             command:
               - "/bin/sh"
               - "-c"
               - |
                 set -euo pipefail
                 pip install --no-cache-dir fastapi uvicorn[standard] pillow onnxruntime numpy
                 python /app/inference-app.py
             ports:
               - containerPort: 9000
             volumeMounts:
               - name: app-code
                 mountPath: /app
         volumes:
           - name: app-code
             configMap:
               name: vehicle-detector-code
   ---
   apiVersion: v1
   kind: Service
   metadata:
     name: vehicle-detector
     namespace: edge-ai
   spec:
     selector:
       app: vehicle-detector
     ports:
       - port: 9000
         targetPort: 9000
   EOF
   kubectl apply -f \
     ~/sugarkube-labs/tutorial-13/workloads/edge-ai/vehicle-detector-configmap.yaml
   kubectl apply -f ~/sugarkube-labs/tutorial-13/workloads/edge-ai/edge-ai-deployment.yaml
   ```

   Ensure the pods enter the `Running` state before proceeding.

3. Forward port 9000 to your workstation and send sample images through the API. Use a Creative
   Commons traffic photo so results are reproducible:

   ```bash
   kubectl port-forward svc/vehicle-detector -n edge-ai 9000:9000
   ```

   In a new terminal, download the image and call the endpoint:

   ```bash
   curl -L -o ~/sugarkube-labs/tutorial-13/edge-ai/traffic.jpg \
     https://upload.wikimedia.org/wikipedia/commons/5/5f/Traffic_in_Singapore%2C_Jan_2016_-_02.jpg
   curl -X POST -F "image=@~/sugarkube-labs/tutorial-13/edge-ai/traffic.jpg" \
     http://localhost:9000/infer | tee ~/sugarkube-labs/tutorial-13/edge-ai/inference.log
   ```

   Stop the port-forward session with `Ctrl+C` once you finish testing.

4. Measure resource usage during inference:

   ```bash
   kubectl top pods -n edge-ai --use-protocol-buffers > \
     ~/sugarkube-labs/tutorial-13/edge-ai/resource-usage.csv
   ```

5. Experiment with tuning parameters such as batch size or CPU pinning, documenting each change and
   the resulting latency in `~/sugarkube-labs/tutorial-13/edge-ai/tuning-experiments.md`.

> [!CAUTION]
> When forwarding ports or streaming data, avoid exposing services to the public internet. Keep
> traffic bound to `localhost` or a trusted VPN, and tear down port-forward sessions with `Ctrl+C`
> once testing ends.

### 6. Optimise and secure the expanded cluster
1. Enable pod disruption budgets (PDBs) for critical services so voluntary disruptions do not drop
   availability:

   ```bash
   kubectl apply -f policies/pdb-core-services.yaml
   ```

2. Run `kubectl get events -A --sort-by=.metadata.creationTimestamp` to surface churn or failures.
   Export the output to `operations/events-post-expansion.log`.

3. Benchmark storage throughput on each node by launching a disposable `fio` job:

   ```bash
   kubectl create job fio-benchmark -n lab-scale \
     --image=ghcr.io/cloud-bulldozer/fio:3.36 -- \
     fio --name=randread --filename=/data/benchmark/testfile --size=1G \
     --rw=randread --bs=4k --iodepth=32 --runtime=60 --time_based --direct=1
   kubectl wait --for=condition=complete job/fio-benchmark -n lab-scale --timeout=10m
   kubectl logs -n lab-scale job/fio-benchmark > \
     ~/sugarkube-labs/tutorial-13/operations/fio-report.log
   kubectl delete job fio-benchmark -n lab-scale
   ```

   Capture `fio` output for the operations runbook.

4. Harden remote access by replacing SSH credential pairs and disabling keyboard-interactive logins.
   Follow the procedure you documented in Tutorial 11 and update
   `operations/security-checklist.md` with the date and fingerprint details.

5. Take a final cluster snapshot:

   ```bash
   kubectl get nodes -o wide > ~/sugarkube-labs/tutorial-13/final/nodes.txt
   kubectl get pods -A -o wide > ~/sugarkube-labs/tutorial-13/final/pods.txt
   kubectl describe storageclass nfs-shared > \
     ~/sugarkube-labs/tutorial-13/final/storageclass.txt
   ```

   Archive these files alongside Grafana dashboards or monitoring exports if available.

## Milestone Checklist
Use this checklist to confirm you met the roadmap milestones.

- [ ] Multi-node prototype: at least two new workers joined, workloads scheduled across them, and
      performance compared against the baseline.
- [ ] Failure-injection exercise: simulated node disruption recovered without data loss,
      with findings logged in `storage/failover-report.md`.
- [ ] Advanced roadmap update: drafted `edge-ai/tuning-experiments.md` and
      `operations/security-checklist.md` summarising optimisation insights and proposed next steps.

## Next Steps
You now possess the full Sugarkube lifecycle—from first boot to advanced experimentation. Continue
iterating by turning your lab notes into proposals on the
[Sugarkube issue tracker](https://github.com/futuroptimist/sugarkube/issues), sharing reproducible
configurations, and mentoring newcomers as they begin
[Tutorial 1](./tutorial-01-computing-foundations.md). When new roadmap items appear, use the
evidence you gathered here to prioritise and scope the next wave of improvements.
