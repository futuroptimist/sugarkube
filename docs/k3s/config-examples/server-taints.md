# Control-plane taints

To keep workloads off the Raspberry Pi control-plane nodes, apply the following taint
once kube-vip and the initial server are online:

```bash
kubectl taint nodes <node-name> \
  node-role.kubernetes.io/control-plane=true:NoSchedule
```

You can confirm the taint is in place with:

```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

If you later decide to schedule workloads onto the control-plane, remove the taint:

```bash
kubectl taint nodes <node-name> \
  node-role.kubernetes.io/control-plane:NoSchedule-
```
