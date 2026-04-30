(function () {
    function cloneNode(node) {
        return node.cloneNode(true);
    }

    function createPage(headerTemplate, footerTemplate) {
        const page = document.createElement("section");
        page.className = "print-only print-sheet print-page";

        const header = cloneNode(headerTemplate);
        const body = document.createElement("div");
        body.className = "print-page-body";
        const footer = cloneNode(footerTemplate);

        page.appendChild(header);
        page.appendChild(body);
        page.appendChild(footer);

        return { page, header, body, footer, maxBodyHeight: 0 };
    }

    function refreshPageMetrics(pageRef) {
        const available = pageRef.page.clientHeight - pageRef.header.offsetHeight - pageRef.footer.offsetHeight;
        pageRef.maxBodyHeight = Math.max(0, available);
    }

    function createAndMountPage(state) {
        state.current = createPage(state.headerTemplate, state.footerTemplate);
        state.output.appendChild(state.current.page);
        refreshPageMetrics(state.current);
    }

    function markCurrentPageContinues(state) {
        if (!state || !state.current || !state.current.page) return;
        state.current.page.dataset.continuesNext = "1";
    }

    function fitsInCurrentPage(pageRef) {
        return pageRef.body.scrollHeight <= (pageRef.maxBodyHeight + 1);
    }

    function applyPageCountersAndState(output, options) {
        const pages = Array.from(output.querySelectorAll(".print-page"));
        const total = pages.length;
        const hideContinuationFooter = Boolean(options && options.hideContinuationFooter);

        pages.forEach((page, index) => {
            const current = index + 1;
            page.querySelectorAll(".print-page-current").forEach((el) => {
                el.textContent = String(current);
            });
            page.querySelectorAll(".print-page-total").forEach((el) => {
                el.textContent = String(total);
            });

            const footerState = page.querySelector(".print-footer-state");
            if (!footerState) return;

            const shouldShowContinuation = page.dataset.continuesNext === "1";
            if (hideContinuationFooter && shouldShowContinuation) {
                footerState.textContent = "";
                return;
            }
            if (shouldShowContinuation) {
                footerState.textContent = "CONTINUA NA PROXIMA PAGINA";
                return;
            }
            footerState.textContent = current === total ? "FIM DO RELATORIO" : "";
        });
    }

    function appendBlockWithOptionalTitle(state, blockNode, titleNode) {
        const titleClone = titleNode ? cloneNode(titleNode) : null;
        const blockClone = cloneNode(blockNode);

        if (titleClone) state.current.body.appendChild(titleClone);
        state.current.body.appendChild(blockClone);

        if (fitsInCurrentPage(state.current)) return;

        if (titleClone) titleClone.remove();
        blockClone.remove();

        markCurrentPageContinues(state);
        createAndMountPage(state);

        if (titleClone) state.current.body.appendChild(titleClone);
        state.current.body.appendChild(blockClone);
    }

    function appendTableSplitByRows(state, tableNode, sectionTitleNode) {
        const sourceHead = tableNode.querySelector(":scope > thead");
        const sourceBody = tableNode.querySelector(":scope > tbody");
        const sourceColgroup = tableNode.querySelector(":scope > colgroup");
        const rows = sourceBody ? Array.from(sourceBody.querySelectorAll(":scope > tr")) : [];

        if (!sourceHead || !sourceBody || !rows.length) {
            appendBlockWithOptionalTitle(state, tableNode, sectionTitleNode);
            return;
        }

        function buildTableShell() {
            const table = tableNode.cloneNode(false);
            if (sourceColgroup) {
                table.appendChild(cloneNode(sourceColgroup));
            }
            table.appendChild(cloneNode(sourceHead));
            table.appendChild(sourceBody.cloneNode(false));
            return table;
        }

        function createPageTable(withContinuationTitle) {
            if (withContinuationTitle) {
                markCurrentPageContinues(state);
                createAndMountPage(state);
            }
            if (sectionTitleNode) {
                const repeatedTitle = cloneNode(sectionTitleNode);
                if (withContinuationTitle && !state.hideContinuationTitle) {
                    repeatedTitle.textContent = repeatedTitle.textContent + " (continuacao)";
                }
                state.current.body.appendChild(repeatedTitle);
            }
            const pageTable = buildTableShell();
            state.current.body.appendChild(pageTable);
            return pageTable.querySelector(":scope > tbody");
        }

        let pageBody = createPageTable(false);
        rows.forEach((row) => {
            const rowClone = cloneNode(row);
            pageBody.appendChild(rowClone);

            if (fitsInCurrentPage(state.current)) return;

            rowClone.remove();
            const pageIsEmpty = pageBody.children.length === 0;
            if (pageIsEmpty) {
                pageBody.appendChild(rowClone);
                return;
            }

            pageBody = createPageTable(true);
            pageBody.appendChild(rowClone);
        });
    }

    function appendTreeSplitByItems(state, treeNode, sectionTitleNode) {
        const items = Array.from(treeNode.querySelectorAll(":scope > .print-tree-item"));
        if (!items.length) {
            appendBlockWithOptionalTitle(state, treeNode, sectionTitleNode);
            return;
        }

        let treeContainer = treeNode.cloneNode(false);

        function startNewPageWithTitle(asContinuation) {
            markCurrentPageContinues(state);
            createAndMountPage(state);

            if (sectionTitleNode) {
                const repeatedTitle = cloneNode(sectionTitleNode);
                if (asContinuation && !state.hideContinuationTitle) {
                    repeatedTitle.textContent = repeatedTitle.textContent + " (continuacao)";
                }
                state.current.body.appendChild(repeatedTitle);
            }

            treeContainer = treeNode.cloneNode(false);
            state.current.body.appendChild(treeContainer);
        }

        if (sectionTitleNode) {
            state.current.body.appendChild(cloneNode(sectionTitleNode));
        }
        state.current.body.appendChild(treeContainer);

        items.forEach((item) => {
            const itemClone = cloneNode(item);
            treeContainer.appendChild(itemClone);

            if (fitsInCurrentPage(state.current)) return;

            itemClone.remove();

            const treeIsEmpty = treeContainer.children.length === 0;
            if (treeIsEmpty) {
                treeContainer.appendChild(itemClone);
                return;
            }

            startNewPageWithTitle(true);
            treeContainer.appendChild(itemClone);
        });
    }

    function appendRecordCardsSplitByItems(state, listNode, sectionTitleNode, continuationHeaderNode) {
        const items = Array.from(listNode.querySelectorAll(":scope > .print-record-card"));
        if (!items.length) {
            if (continuationHeaderNode) {
                appendBlockWithOptionalTitle(state, continuationHeaderNode, sectionTitleNode);
                appendBlockWithOptionalTitle(state, listNode, null);
                return;
            }
            appendBlockWithOptionalTitle(state, listNode, sectionTitleNode);
            return;
        }

        if (state.breakPerRecord) {
            items.forEach((item, index) => {
                if (index > 0) {
                    createAndMountPage(state);
                }
                if (sectionTitleNode) {
                    state.current.body.appendChild(cloneNode(sectionTitleNode));
                }
                if (continuationHeaderNode) {
                    state.current.body.appendChild(cloneNode(continuationHeaderNode));
                }
                const singleListContainer = listNode.cloneNode(false);
                singleListContainer.appendChild(cloneNode(item));
                state.current.body.appendChild(singleListContainer);
            });
            return;
        }

        let listContainer = listNode.cloneNode(false);

        function startNewPageWithTitle(asContinuation) {
            markCurrentPageContinues(state);
            createAndMountPage(state);

            if (sectionTitleNode) {
                const repeatedTitle = cloneNode(sectionTitleNode);
                if (asContinuation && !state.hideContinuationTitle) {
                    repeatedTitle.textContent = repeatedTitle.textContent + " (continuacao)";
                }
                state.current.body.appendChild(repeatedTitle);
            }
            if (continuationHeaderNode) {
                state.current.body.appendChild(cloneNode(continuationHeaderNode));
            }

            listContainer = listNode.cloneNode(false);
            state.current.body.appendChild(listContainer);
        }

        if (sectionTitleNode) {
            state.current.body.appendChild(cloneNode(sectionTitleNode));
        }
        if (continuationHeaderNode) {
            state.current.body.appendChild(cloneNode(continuationHeaderNode));
        }
        state.current.body.appendChild(listContainer);

        items.forEach((item) => {
            const itemClone = cloneNode(item);
            listContainer.appendChild(itemClone);

            if (fitsInCurrentPage(state.current)) return;

            itemClone.remove();

            const listIsEmpty = listContainer.children.length === 0;
            if (listIsEmpty) {
                listContainer.appendChild(itemClone);
                return;
            }

            startNewPageWithTitle(true);
            listContainer.appendChild(itemClone);
        });
    }

    function prepareReport(report) {
        const headerTemplate = report.querySelector(":scope > .print-header");
        const footerTemplate = report.querySelector(":scope > .print-footer");
        if (!headerTemplate || !footerTemplate) return;

        let output = report.nextElementSibling;
        if (!output || !output.classList.contains("print-pages-output")) {
            output = document.createElement("div");
            output.className = "print-only print-pages-output";
            report.insertAdjacentElement("afterend", output);
        }
        output.innerHTML = "";

        const nodes = Array.from(report.children).filter(
            (node) => !node.classList.contains("print-header") && !node.classList.contains("print-footer")
        );

        const state = {
            headerTemplate: headerTemplate,
            footerTemplate: footerTemplate,
            output: output,
            current: null,
            hideContinuationFooter: report.dataset.hideContinuationFooter === "1",
            hideContinuationTitle: report.dataset.hideContinuationTitle === "1",
            breakPerRecord: report.dataset.breakPerRecord === "1",
        };

        createAndMountPage(state);

        let pendingSectionTitle = null;
        nodes.forEach((node) => {
            if (node.classList.contains("print-force-page-break")) {
                createAndMountPage(state);
                pendingSectionTitle = null;
                return;
            }

            if (node.classList.contains("print-section-title")) {
                pendingSectionTitle = node;
                return;
            }

            if (node.classList.contains("print-tree")) {
                appendTreeSplitByItems(state, node, pendingSectionTitle);
                pendingSectionTitle = null;
                return;
            }

            if (
                node.classList.contains("print-data-table")
                && node.classList.contains("print-split-rows")
            ) {
                appendTableSplitByRows(state, node, pendingSectionTitle);
                pendingSectionTitle = null;
                return;
            }

            if (node.classList.contains("print-record-list")) {
                let continuationHeaderNode = null;
                const previousElement = node.previousElementSibling;
                if (previousElement && previousElement.classList.contains("print-dashboard-list-head")) {
                    continuationHeaderNode = previousElement;
                }
                appendRecordCardsSplitByItems(state, node, pendingSectionTitle, continuationHeaderNode);
                pendingSectionTitle = null;
                return;
            }

            appendBlockWithOptionalTitle(state, node, pendingSectionTitle);
            pendingSectionTitle = null;
        });

        applyPageCountersAndState(output, state);
    }

    function prepareAllReports() {
        const reports = Array.from(document.querySelectorAll(".js-print-report"));
        document.body.classList.add("print-pagination-measure");
        reports.forEach((report) => prepareReport(report));
        document.body.classList.remove("print-pagination-measure");
        if (reports.length) {
            document.body.classList.add("print-pagination-ready");
        }
    }

    window.runStandardPrint = function () {
        prepareAllReports();
        window.setTimeout(function () {
            window.print();
        }, 30);
    };

    window.addEventListener("beforeprint", prepareAllReports);
})();
