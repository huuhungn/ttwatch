# Code-signing the exe with SignPath Foundation (free)

> **Optional.** Authenticode signing only reduces SmartScreen warnings. The app works normally without it. Releases already ship with a SHA256 file and a Sigstore provenance attestation (see the README); neither needs any account registration.

The released exe is currently unsigned, so Windows SmartScreen may show a warning. `release.yml` already contains a signing step, but it **only runs when** the build comes from a tag **and** the repo has the `SIGNPATH_ORGANIZATION_ID` variable. Until it is configured, releases build normally and stay unsigned.

## SignPath Foundation requirements

Per [signpath.org/terms](https://signpath.org/terms): an OSI-approved license (MIT qualifies), public source, a released and still-maintained project, a home page that describes what it does, and no proprietary code or unwanted software. The signing team must be the team that maintains **all** of the source code and build scripts of the signed part. Every member must use two-factor authentication on both SignPath and GitHub.

Assess the "all source code belongs to the team" requirement honestly: if any code remains whose origin or usage rights you are unsure about, do not apply until that is resolved. Third-party libraries in the `_internal` folder may stay unsigned; only `ttwatch.exe` is signed.

## Steps (done by the repo owner, using your own accounts)

1. Two-factor authentication (2FA): check <https://github.com/settings/security> for each member account, and turn on *Require two-factor authentication* for the `huuhungn` organization (Settings → Authentication security). The API does not reveal personal 2FA status, so you have to check that page yourself.
2. Apply at <https://signpath.org/apply>. Beforehand, prepare a **Code signing policy** section in the README or on the download page (see the template below); publish it only once the application is accepted, so it never states something untrue.
3. After approval, create a project in SignPath (the default slug the workflow uses is `ttwatch`) and a signing policy `release-signing`; add the *GitHub.com* Trusted Build System and link it to the project; install the [SignPath GitHub App](https://github.com/apps/signpath) on the repo.
4. In the project, create the default *Artifact configuration*:

   ```xml
   <artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
     <zip-file>
       <pe-file path="ttwatch.exe">
         <authenticode-sign/>
       </pe-file>
     </zip-file>
   </artifact-configuration>
   ```

5. Create an API token for a user with the *submitter* role. In GitHub (Settings → Secrets and variables → Actions) add:
   - secret `SIGNPATH_API_TOKEN`: the token you just created;
   - variable `SIGNPATH_ORGANIZATION_ID`: the SignPath organization ID;
   - (optional) variables `SIGNPATH_PROJECT_SLUG` and `SIGNPATH_POLICY_SLUG` if you chose slugs other than `ttwatch` / `release-signing`.
6. Push a `v*` tag as usual. The workflow submits a signing request, waits up to 1 hour for the approver to approve it in SignPath, replaces `ttwatch.exe` with the signed one, checks that `Get-AuthenticodeSignature` reports `Valid`, then smoke-tests the exe and zips it.

## "Code signing policy" section template (put it in the README after approval)

> ## Code signing policy
>
> Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).
>
> - Committers and reviewers: [anhtahaylove](https://github.com/anhtahaylove)
> - Approvers: [anhtahaylove](https://github.com/anhtahaylove)
>
> Privacy policy: this program does not send information to any other networked system unless the user specifically requests it (the tool only accesses public TikTok pages, using a browser on your machine).

## Notes

- A certificate issued by SignPath Foundation names SignPath Foundation as the publisher, not you.
- A freshly signed exe may still trigger SmartScreen warnings until it builds reputation through downloads.
- Manual builds (`workflow_dispatch`) are not signed; only builds from a tag are.
