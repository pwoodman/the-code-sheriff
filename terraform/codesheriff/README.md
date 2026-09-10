# Terraform module for The Code Sheriff

Customer-owned module. It does not provision a Sheriff-operated control
plane. Outputs a `quality.toml` fragment plus placeholders for GitHub
rulesets, model-provider env, budgets, and team mappings.

```hcl
module "codesheriff" {
  source      = "./terraform/codesheriff"
  repo        = "acme/app"
  policy      = "adopt"
  provider_name = "auto"
  monthly_cap = 0
}
```

Apply the `quality_toml` output in the target repository. GitHub App
install and Actions minutes stay on the customer org.
