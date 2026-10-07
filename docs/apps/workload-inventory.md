# Application workload inventory

`config/workload-inventory/profiles.json` records the reviewed chart coordinates,
source repositories and source paths for the local relay, published relay and
published DSPACE charts. `scripts/app_chart.py` applies these profiles during
render validation. Other external charts retain the generic render checks.

Each profile requires exactly one Deployment and one Service, with at most one
of each listed optional resource. The primary container name and image repository
are fixed; the image tag must exactly match the requested tag. Sidecars, init
containers, ephemeral containers, extra workloads, Lists, unknown resource kinds
and Helm hooks fail validation, including resources without release labels.
Deployment and Service names follow the chart's name and fullname overrides.
Selectors must agree with pod labels and the requested release. Explicit resource
and pod namespaces and Helm release annotations must not conflict with the
requested namespace. Omitted namespaces inherit the Helm release namespace.

Published DSPACE's optional Secret remains forbidden. Its source path is
`charts/dspace`; the separate `deploy/charts/dspace` layout contains a Helm test
Pod and has no supported inventory profile. Do not enable that layout by adding
Pod or hook exceptions to the published profile.

The offline DSPACE promotion planner supplies the published chart origin only
after validating its artifact and source reports. It passes the archive digest
to the shared validator, which rechecks the local archive bytes. A local archive
filename alone does not establish published provenance. OCI references select a
profile by exact registry coordinate, including digest-qualified references;
existing chart version and provenance checks remain in force.

Inventory validation does not impose replica counts or alter autoscaling. The
promotion planner retains its separate two-replica rehearsal requirement. The
supported chart layouts do not currently render an HPA; adding a new layout or
resource requires a reviewed profile update rather than a global exception.

Offline fixtures in `tests/fixtures/workload_inventory` and
`tests/test_workload_inventory.py` cover valid inventories, varying replica counts,
archive binding and rejected identity, namespace, selector and workload changes.

The published DSPACE render fixture comes from source revision
`22f506e07e0b5abfd0cf756e9c5827c0458fb4b2`, path `charts/dspace`, with the repository's
dev and staging values and the synthetic image tag `main-deadbee`. A separate test
renders the checked-in local relay chart with Helm when Helm is available.

The fixture quotes the service account token mounting field name to avoid a
false positive from the diff secret scanner; its value remains false.

A custom release can satisfy the workload inventory while failing the separate
application metrics inventory. The existing token.place metrics configuration
names the default release; a custom release does not bypass that check.
