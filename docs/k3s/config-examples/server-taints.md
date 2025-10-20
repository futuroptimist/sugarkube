# Control-plane taints

To keep application workloads off the control-plane nodes, apply the following taints after
bootstrapping the three-server HA cluster:

```bash
kubectl taint nodes \
  $(kubectl get nodes -l node-role.kubernetes.io/control-plane= -o name) \
  node-role.kubernetes.io/control-plane=true:NoSchedule --overwrite
```

When a workload must run on the control-plane nodes (for example kube-vip or etcd maintenance
jobs), add tolerations similar to:

```yaml
spec:
  tolerations:
    - key: "node-role.kubernetes.io/control-plane"
      operator: "Exists"
      effect: "NoSchedule"
```
