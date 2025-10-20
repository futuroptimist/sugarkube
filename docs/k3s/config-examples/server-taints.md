# Control-plane taints

The Pi 5 control-plane nodes ship with enough CPU and RAM to host light
workloads, but production clusters benefit from isolating them to Kubernetes
control-plane services only. Apply the following taint on each server to prevent
workloads that lack a toleration from landing on the control-plane:

```bash
kubectl taint nodes <hostname> node-role.kubernetes.io/control-plane=true:NoSchedule
```

If you need to schedule a DaemonSet (for example, kube-vip or promtail) on the
control-plane, add a matching toleration:

```yaml
tolerations:
  - key: node-role.kubernetes.io/control-plane
    operator: Exists
    effect: NoSchedule
```

Remove the taint temporarily for maintenance windows with:

```bash
kubectl taint nodes <hostname> node-role.kubernetes.io/control-plane-
```
