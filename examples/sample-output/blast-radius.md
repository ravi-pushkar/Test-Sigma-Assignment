# Blast-radius report: PR #37045

## What changed

[Refactor issue sidebar and fix various problems](https://github.com/go-gitea/gitea/pull/37045) changes 21 files from `daf581fa` to `e7095e09`.

## Executive summary

7 changed code areas map to 116 UI elements across 14 screens. 2 of 3 discovered user flows touch affected elements or screens.

1 ingested requirements are linked to affected UI.

## Impacts by risk

### 🔴 HIGH — templates/repo/issue/new_form.tmpl

Changes to templates/repo/issue/new_form.tmpl affect Write Preview Drop files or click here …, Title, Create Issue across /{owner}/{repo}/issues/new.

Affected user flows: Create a new issue in the demo/demo-repo repository titled "Crawler-created issue for flow F2"

Confidence: 84%.

Evidence: `pr_change:410b2eb5d07cb116 → symbol:c0a8f526c199bd93 → element:29539cd1384e641e → screen:5a48dd062840932f`; `pr_change:410b2eb5d07cb116 → symbol:c0a8f526c199bd93 → element:2eb54f4318a32d01 → screen:5a48dd062840932f → flow:aac91c7b466a1b03`; `pr_change:410b2eb5d07cb116 → symbol:c0a8f526c199bd93 → element:aa1ce2d4bde100b7 → screen:5a48dd062840932f → flow:aac91c7b466a1b03`

### 🟠 MEDIUM — templates/base/head_navbar_icons.tmpl

Changes to templates/base/head_navbar_icons.tmpl affect Notifications (12 places) across /, /issues, /{owner}/{repo}/issues/{number}, /{owner}/{repo}/issues/new, /{owner}/{repo}.

Confidence: 65%.

Evidence: `pr_change:c0c791af90d43a24 → symbol:8d5c371379440ad5 → element:00cc9758f2540469 → screen:719668836539fa4d`; `pr_change:c0c791af90d43a24 → symbol:8d5c371379440ad5 → element:3041dfbfb53151c4 → screen:5b42ad8771ae5cc6`; `pr_change:c0c791af90d43a24 → symbol:8d5c371379440ad5 → element:4b1e9a4263889c03 → screen:e4f0d72d0bc9f3f6`; `pr_change:c0c791af90d43a24 → symbol:8d5c371379440ad5 → element:680bdb5dc16fce2a → screen:6d84ae07140a28c2`; `pr_change:c0c791af90d43a24 → symbol:8d5c371379440ad5 → element:681dc910590013c9 → screen:bdc0677de42ce85e`

… plus 7 more recorded paths (see impact records).

### 🟠 MEDIUM — web_src/js/features/repo-issue.ts

Changes to web_src/js/features/repo-issue.ts affect Edit (4 places) across /{owner}/{repo}/issues/{number}.

Confidence: 55%.

Evidence: `pr_change:67d24e2c903af2b8 → symbol:6317da3fe0a4a509 → element:922c799c50a2db2d → screen:4d770bec6fd73d44`; `pr_change:67d24e2c903af2b8 → symbol:6317da3fe0a4a509 → element:d828077325b7646f → screen:8db40db8243cfe7f`; `pr_change:67d24e2c903af2b8 → symbol:6317da3fe0a4a509 → element:ec56bcd93ccf4ba9 → screen:e40201cb68369f23`; `pr_change:67d24e2c903af2b8 → symbol:6317da3fe0a4a509 → element:f4b4ddf5b97fbef7 → screen:bdc0677de42ce85e`

### 🟠 MEDIUM — templates/repo/issue/view_content/watching.tmpl

Changes to templates/repo/issue/view_content/watching.tmpl affect Unsubscribe (4 places), Subscribe (4 places) across /{owner}/{repo}/issues/{number}.

Affected user flows: In demo/demo-repo, open the issue titled "Sidebar labels are not saved on first click" and subscribe to notifications for it using the Watch/Subscribe button in the issue sidebar.

Confidence: 65%.

Evidence: `pr_change:271c02b3fa8c8f97 → symbol:fb4625d8fb61f92e → element:1dea30f7787f6811 → screen:bdc0677de42ce85e`; `pr_change:271c02b3fa8c8f97 → symbol:fb4625d8fb61f92e → element:286ec3b26dce39d6 → screen:4d770bec6fd73d44`; `pr_change:271c02b3fa8c8f97 → symbol:fb4625d8fb61f92e → element:33011a7854187297 → screen:e40201cb68369f23 → flow:7b377f25cf0b2779`; `pr_change:271c02b3fa8c8f97 → symbol:fb4625d8fb61f92e → element:3c2c401254cc2801 → screen:8db40db8243cfe7f`; `pr_change:271c02b3fa8c8f97 → symbol:fb4625d8fb61f92e → element:81e1d0c744e3cc49 → screen:8db40db8243cfe7f`

… plus 3 more recorded paths (see impact records).

### 🟠 MEDIUM — templates/repo/issue/view_content.tmpl

Changes to templates/repo/issue/view_content.tmpl affect Comment (4 places), Write Preview Drop files or click here … (4 places), Close Issue (4 places) across /{owner}/{repo}/issues/{number}.

Confidence: 84%.

Evidence: `pr_change:05f6bd86a139b49e → symbol:9fa55fe0677390c4 → element:0a808cbe0d3ca4ed → screen:4d770bec6fd73d44`; `pr_change:05f6bd86a139b49e → symbol:9fa55fe0677390c4 → element:2c94fee3760e269a → screen:8db40db8243cfe7f`; `pr_change:05f6bd86a139b49e → symbol:9fa55fe0677390c4 → element:642472685127abf4 → screen:8db40db8243cfe7f`; `pr_change:05f6bd86a139b49e → symbol:9fa55fe0677390c4 → element:6e3aebd2fd9ea857 → screen:e40201cb68369f23`; `pr_change:05f6bd86a139b49e → symbol:9fa55fe0677390c4 → element:73bcbc1e6014f789 → screen:8db40db8243cfe7f`

… plus 7 more recorded paths (see impact records).

### 🟠 MEDIUM — templates/base/head_navbar.tmpl

Changes to templates/base/head_navbar.tmpl affect Milestones (12 places), Issues (12 places), Dashboard (12 places), Pull Requests (12 places), Explore (14 places), New Repository (5 places), and 2 more across /issues, /, /user/login, /{owner}/{repo}, /{owner}/{repo}/issues/{number}, and 1 more.

Affected user flows: Create a new issue in the demo/demo-repo repository titled "Crawler-created issue for flow F2"

Confidence: 65%.

Evidence: `pr_change:8995990d0673de8d → symbol:47863527ceb12629 → element:10ba32600fb398a1 → screen:e4f0d72d0bc9f3f6`; `pr_change:8995990d0673de8d → symbol:47863527ceb12629 → element:151796047e18f4a8 → screen:5b42ad8771ae5cc6`; `pr_change:8995990d0673de8d → symbol:47863527ceb12629 → element:1963b347cc56a791 → screen:719668836539fa4d`; `pr_change:8995990d0673de8d → symbol:47863527ceb12629 → element:2312f0f2df95ef5a → screen:e4f0d72d0bc9f3f6`; `pr_change:8995990d0673de8d → symbol:47863527ceb12629 → element:2322cd664b4d05fa → screen:6d84ae07140a28c2`

… plus 66 more recorded paths (see impact records).

### 🟠 MEDIUM — templates/repo/issue/sidebar/project_list.tmpl

Changes to templates/repo/issue/sidebar/project_list.tmpl affect Projects (6 places) across /{owner}/{repo}, /{owner}/{repo}/issues/{number}, /{owner}/{repo}/issues/new.

Confidence: 65%.

Evidence: `pr_change:8d62663f5157b1b4 → symbol:0b0ce9e8bd200171 → element:097dc91d92a33f29 → screen:05e983759a5045db`; `pr_change:8d62663f5157b1b4 → symbol:0b0ce9e8bd200171 → element:12df8083b3ee8198 → screen:bdc0677de42ce85e`; `pr_change:8d62663f5157b1b4 → symbol:0b0ce9e8bd200171 → element:5201212d28b9bfc8 → screen:8db40db8243cfe7f`; `pr_change:8d62663f5157b1b4 → symbol:0b0ce9e8bd200171 → element:844fcf7d1152f3d7 → screen:5a48dd062840932f`; `pr_change:8d62663f5157b1b4 → symbol:0b0ce9e8bd200171 → element:a6bf8285e1f59b8e → screen:e40201cb68369f23`

… plus 1 more recorded paths (see impact records).

## User flows to re-test

- In demo/demo-repo, open the issue titled "Sidebar labels are not saved on first click" and subscribe to notifications for it using the Watch/Subscribe button in the issue sidebar. (2 steps)
- Create a new issue in the demo/demo-repo repository titled "Crawler-created issue for flow F2" (8 steps)

## Requirements at risk

- A repository owner can create labels by going to Issues and clicking on Labels.

## Not mapped to UI

These changed files could not be mapped to the discovered UI and remain explicit uncertainty:

- `models/issues/issue_project.go` (modified): no UI link found
- `models/project/column.go` (modified): no UI link found
- `routers/web/repo/issue_new.go` (modified): no UI link found
- `routers/web/repo/issue_page_meta.go` (modified): no UI link found
- `services/projects/issue.go` (modified): no UI link found
- `templates/repo/issue/view_content/sidebar.tmpl` (modified): no UI link found
- `templates/shared/issuelist.tmpl` (modified): no UI link found
- `web_src/css/modules/button.css` (modified): no symbols extracted
- `web_src/css/modules/label.css` (modified): no symbols extracted
- `web_src/js/features/repo-issue-sidebar-combolist.test.ts` (added): no UI link found
- `web_src/js/features/repo-issue-sidebar-combolist.ts` (modified): no UI link found
- `web_src/js/features/repo-issue-sidebar.md` (modified): no symbols extracted
- `web_src/js/features/repo-issue-sidebar.ts` (modified): no UI link found
- `web_src/js/index.ts` (modified): no UI link found

## Run identifiers

- Run ID: `run-m3-nollm-4`
- Source revision: `daf581fa892320f5d495b4073d6812b0ad8ddfc8`
- PR base SHA: `daf581fa892320f5d495b4073d6812b0ad8ddfc8`
- PR head SHA: `e7095e0957a6b46273c2c21afff3450543cb8257`
- Generated at: 2026-07-14T12:20:10.398757+00:00
