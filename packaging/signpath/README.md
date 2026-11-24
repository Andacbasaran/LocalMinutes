# SignPath.io Free Open-Source Code Signing Guide

**LocalMinutes** publishes SHA-256 checksums (`SHA256SUMS.txt`) alongside every Windows, macOS, and Linux release artifact. Windows SmartScreen may still show an "Unknown Publisher" prompt for new downloads until release binaries are signed by a trusted public Certificate Authority.

[SignPath Foundation](https://signpath.org/) provides **free EV/OV code signing** for eligible open-source projects via GitHub Actions.

## Steps to Activate SignPath.io for LocalMinutes

1. **Apply for the SignPath Open Source Program:**
   - Submit `https://github.com/Andacbasaran/LocalMinutes` at [https://signpath.org/terms](https://signpath.org/terms).
   - `LICENSE` (MIT), `SECURITY.md`, and reproducible GitHub Actions releases (`.github/workflows/release.yml`) are already configured.
2. **Create SignPath Project & Artifact Configuration:**
   - Organization slug: `localminutes`
   - Project slug: `localminutes`
   - Signing policy: `release-signing` (maintainer approval required for tagged releases).
3. **Add GitHub Repository Secrets:**
   - `SIGNPATH_API_TOKEN`
   - `SIGNPATH_ORGANIZATION_ID`
4. **Integrate the SignPath Action in `.github/workflows/release.yml`:**
   ```yaml
   - name: Submit Windows artifacts to SignPath.io
     if: startsWith(github.ref, 'refs/tags/v') && secrets.SIGNPATH_API_TOKEN != ''
     uses: signpath/github-action-submit-signing-request@v1
     with:
       api-token: ${{ secrets.SIGNPATH_API_TOKEN }}
       organization-id: ${{ secrets.SIGNPATH_ORGANIZATION_ID }}
       project-slug: localminutes
       artifact-configuration-slug: release-zip
       signing-policy-slug: release-signing
       github-artifact-id: ${{ steps.upload.outputs.artifact-id }}
       wait-for-completion: true
       output-artifact-directory: signed_out
   ```
5. **Regenerate `SHA256SUMS.txt`:** Compute SHA-256 checksums after signing and publish via GitHub Releases.
