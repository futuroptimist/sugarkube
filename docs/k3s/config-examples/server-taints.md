# Control-plane taints for Pi 5 k3s clusters

By default we keep workloads off the control-plane nodes to preserve CPU and IO for etcd.
Apply the following taints once the node registers:

```bash
kubectl taint nodes sugar-prod-cp1 node-role.kubernetes.io/control-plane=true:NoSchedule
kubectl taint nodes sugar-prod-cp2 node-role.kubernetes.io/control-plane=true:NoSchedule
kubectl taint nodes sugar-prod-cp3 node-role.kubernetes.io/control-plane=true:NoSchedule
```

If a workload must run on the control-plane (e.g. kube-vip), annotate it with matching tolerations.
