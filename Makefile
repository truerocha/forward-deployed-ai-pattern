# Makefile — Forward Deployed AI Pattern

.PHONY: setup-hooks mirror mirror-dry-run profile

setup-hooks:
	@echo "Installing git hooks..."
	@cp scripts/hooks/pre-push .git/hooks/pre-push
	@chmod +x .git/hooks/pre-push
	@echo "✅ pre-push hook installed"

profile:
	@if [ -z "$(LEVEL)" ]; then echo "Usage: make profile LEVEL=starter|standard|full"; exit 1; fi
	@if [ ! -f ".kiro/profiles/$(LEVEL).json" ]; then echo "❌ Profile '$(LEVEL)' not found"; exit 1; fi
	@echo "Activating profile: $(LEVEL)"
	@HOOKS=$$(python3 -c "import json; print(' '.join(json.load(open('.kiro/profiles/$(LEVEL).json'))['hooks']))"); \
	for hook in .kiro/hooks/*.kiro.hook; do \
		name=$$(basename "$$hook" .kiro.hook); \
		if echo "$$HOOKS" | grep -qw "$$name"; then \
			echo "  ✅ $$name (active)"; \
		else \
			echo "  ⏸️  $$name (inactive in $(LEVEL) profile)"; \
		fi; \
	done
	@echo ""
	@echo "Profile '$(LEVEL)' activated. See docs/quickstart.md for next steps."

mirror:
	@bash scripts/mirror-push.sh

mirror-dry-run:
	@bash scripts/mirror-push.sh --dry-run
