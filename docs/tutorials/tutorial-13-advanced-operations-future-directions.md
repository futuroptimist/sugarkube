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
   kubectl get nodes -o wide
   kubectl get pods -A -o wide
   ```

   Save the output to `baseline/cluster-inventory.txt` in your lab directory.

3. Capture current resource utilisation using `kubectl top` (requires metrics-server):

   ```bash
   kubectl top nodes
   kubectl top pods -A
   ```

   Export the results to `baseline/resource-snapshot.csv` so you can compare post-expansion metrics.

> [!TIP]
> If `kubectl top` fails, redeploy metrics-server using the manifests in
> `deployments/metrics-server/` from the repository. Rerun the commands once the API reports
> healthy.

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
   curl -sfL https://get.k3s.io | \
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

2. Deploy the `kube-burner` Helm chart or a similar load generator. This example uses a prebuilt
   chart stored under `deployments/kube-burner/values.yaml`:

   ```bash
   helm upgrade --install kube-burner ./deployments/kube-burner \
     --namespace lab-scale \
     --set replicaCount=4 \
     --set jobIterations=200
   ```

3. Monitor pod placement to confirm workloads spread across nodes:

   ```bash
   watch -n5 kubectl get pods -n lab-scale -o wide
   ```

   Capture screenshots or copy the watch output to `expansion/pod-distribution.txt`.

4. When the job completes, gather metrics:

   ```bash
   kubectl logs job/kube-burner -n lab-scale > expansion/kube-burner-report.log
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

2. Apply the manifest and confirm the class exists:

   ```bash
   kubectl apply -f storage/nfs-storageclass.yaml
   kubectl get storageclass
   ```

3. Deploy a sample StatefulSet to validate durability:

   ```bash
   kubectl apply -f storage/statefulset-sqlite.yaml
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
   intact. Document the observation in `storage/failover-report.md`.

> [!NOTE]
> If the PVC enters `Pending`, ensure the NFS export allows the worker node IPs and that the
> firewall exposes TCP/2049. Run `showmount -e <server>` from each node to verify connectivity.

### 5. Launch an edge AI workload
1. Create a dedicated namespace:

   ```bash
   kubectl create namespace edge-ai
   ```

2. Deploy a lightweight model, such as `openvino/vehicle-detection`:

   ```bash
   helm upgrade --install vehicle-detector ./deployments/edge-ai \
     --namespace edge-ai \
     --set replicaCount=2 \
     --set resources.limits.cpu=500m \
     --set resources.limits.memory=512Mi
   ```

   Ensure the Helm chart pulls container images compatible with your node architecture.

3. Stream sample video frames to the service:

   ```bash
   kubectl port-forward svc/vehicle-detector -n edge-ai 9000:9000
   ffmpeg -re -i samples/edge-ai/traffic.mp4 -f image2 \
     -update 1 http://localhost:9000/infer
   ```

   Record the container logs to `edge-ai/inference.log` for later analysis.

4. Measure resource usage during inference:

   ```bash
   kubectl top pods -n edge-ai --use-protocol-buffers > edge-ai/resource-usage.csv
   ```

5. Experiment with tuning parameters such as batch size or CPU pinning, documenting each change and
   the resulting latency in `edge-ai/tuning-experiments.md`.

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

3. Benchmark storage throughput on each node:

   ```bash
   kubectl exec -n lab-scale deploy/kube-burner -- fio --name=randread \
     --filename=/data/benchmark/testfile --size=1G --rw=randread --bs=4k \
     --iodepth=32 --runtime=60 --time_based --direct=1
   ```

   Capture `fio` output for the operations runbook.

4. Harden remote access by replacing SSH credential pairs and disabling keyboard-interactive logins.
   Follow the procedure you documented in Tutorial 11 and update
   `operations/security-checklist.md` with the date and fingerprint details.

5. Take a final cluster snapshot:

   ```bash
   kubectl get nodes -o wide > final/nodes.txt
   kubectl get pods -A -o wide > final/pods.txt
   kubectl describe storageclass nfs-shared > final/storageclass.txt
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
