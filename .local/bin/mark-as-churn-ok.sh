#!/usr/bin/env sh
PR="${1:?You must supply a PR# to recieve the label}"
gh pr edit $PR --add-label 'churn-ok'
