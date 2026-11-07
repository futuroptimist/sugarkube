# Historical runtime fixture

`target-ethernet-quorum-recover.py.gz` is the exact public controller source from
`b320c583a39d9771548bff9cd684bf3c08b82caf:scripts/ethernet_quorum_recover.py`,
compressed with deterministic gzip metadata. Its uncompressed SHA256 is
`6acb80dcd38ced32a57792fe8eb7dc5ee6ae05099ed51643813fbf4605752201`.

This is immutable test data, never imported or executed. It preserves the original
planner target proof while current controller source evolves. The bytes were
compared to the historical catalog and reviewed as public source, with references
to runtime credential paths but no embedded credentials.

`target-ethernet_etcd_grpc.py.gz` is the exact public native transport source from
`b320c583a39d9771548bff9cd684bf3c08b82caf:scripts/ethernet_etcd_grpc.py`,
compressed with deterministic gzip metadata. Its uncompressed SHA256 is
`aa96cbd77eeb0ab123bf4b1c0c666ea44c891098707974447a3800392e01a28a`.
It is also immutable test data, never imported or executed. Its bytes match the
historical catalog and were reviewed as public source with credential path
references but no embedded credentials. This preserves the historical planner
proof independently of subsequent native transport changes.
