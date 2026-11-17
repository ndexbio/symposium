# Test suites side by side, shared by the repository's Makefile and the data server's.
#
# $(call side_by_side,a b c) runs the targets a, b and c at once (make -k -j), each one's
# output in its own log under $(LOGS), and says as each finishes whether it passed. Once all
# have finished it prints every log in turn, so their outputs never interleave, and fails if
# any failed. Logs rather than --output-sync, which macOS's GNU make 3.81 does not have.
LOGS ?= $(CURDIR)/dist/test-logs

define side_by_side
	@rm -rf "$(LOGS)" && mkdir -p "$(LOGS)"
	@$(MAKE) --no-print-directory -k -j $(words $(1)) $(addprefix log-,$(1)); status=$$?; \
	for target in $(1); do echo "──── $$target"; cat "$(LOGS)/$$target.log"; done; \
	exit $$status
endef

log-%:
	@echo "$*: started"
	@$(MAKE) --no-print-directory $* > "$(LOGS)/$*.log" 2>&1 \
		&& echo "$*: passed" || { echo "$*: FAILED (its log follows below)"; exit 1; }
