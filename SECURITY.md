# Security model

AES-256-GCM authenticates requests and results with job-specific associated
data. Ciphertext confidentiality depends on keeping `SEALED_JOB_KEY_B64`
private. GitHub-hosted runner infrastructure and the repository owner remain
inside the execution trust boundary; this is isolation, not confidential
computing.

Rotate the key immediately if it is logged, committed, exposed in an artifact
or shared outside the private control plane. Treat prior ciphertext as exposed
after a key compromise.

Do not add strategy source, factor definitions, rankings, account identifiers,
positions, holdings, acceptance thresholds or live-trading credentials to this
repository. Plaintext job contents must never be printed.

