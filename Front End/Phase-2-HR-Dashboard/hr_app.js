/**
 * DMRC INTERN REFERRAL WIZARD — RELEASABLE APPS ENGINE
 * Powered natively by Alpine.js reactive state architecture.
 */

// Where the API lives.
//
// DEFAULTS TO EXACTLY WHAT THIS FILE ALREADY HARDCODES, so nothing changes
// behaviour today. To point the dashboard at DMRC's intranet host, set
// window.DMRC_API_BASE in hr_dashboard.html BEFORE this script loads -- one
// line, no code change:
//
//     <script>window.DMRC_API_BASE = 'https://intranet.dmrc.org';</script>
//
// Only the archive's calls read this so far. The rest of this file still has
// its own hardcoded http://127.0.0.1:8000 addresses -- around forty of them,
// and every one will fail on the intranet. Converting them is a separate job
// that touches every screen, and it needs doing before handover.
const API_BASE = (typeof window !== 'undefined' && window.DMRC_API_BASE)
    ? window.DMRC_API_BASE
    : 'http://127.0.0.1:8000';

document.addEventListener('alpine:init', () => {
    Alpine.data('hrCommandCenter', () => ({
        // Global UI State & Assigned Demo Roles
        // The offer letter physically exists only AFTER HR-APP signs and issues
        // it, which moves the application to 'Offer Ready' (the Ready for
        // Handover tab). Before that there is no file to link to. Listed
        // positively rather than as an exclusion list, so a status added later
        // cannot accidentally expose a document that was never generated.
        OFFER_ISSUED_STATUSES: ['Offer Ready', 'Joined', 'Fix Clearance',
                                'Pending Certificate', 'Pending Dispatch', 'Completed'],

        currentRole: 'HR-OPS', 
        roleNames: { 'HR-OPS': 'Dipti', 'HR-APP': 'Reena', 'SYS-ADMIN': 'Varun' },

        // --- IDENTITY (server-resolved) ---
        // currentRole above is only what the UI is currently DISPLAYING. The
        // server independently derives the real role from the users table on
        // every request, so changing this in DevTools grants nothing.
        identity: null,
        isDevMode: null,   // null = not yet answered by the server
        // Dev only: which employee the role switcher impersonates. On the
        // intranet the switcher is hidden and identity comes from the login.
        devEmployeeCodes: {
            'HR-OPS': 'EMP-OHR-001',
            'HR-APP': 'EMP-AHR-001',
            'SYS-ADMIN': 'EMP-ADM-001'
        },
        appView: 'verification_queue', // Can be: verification_queue, authorization_issuance, admin_control_center, college_referrals
        isSidebarCollapsed: false,
        activeTab: 'Pending', 
        showFilterDrawer: false,

        // --- PAGING ------------------------------------------------------
        // Both queues show one page of records at a time. This is a DRAWING
        // limit, not a loading one: the server still sends every record and the
        // browser still filters and sorts all of them, so the master search and
        // the filters stay instant. What it removes is the cost of drawing
        // several hundred rows again on every keystroke and every tick box.
        //
        // The exports are deliberately NOT paged -- see exportQueue and
        // exportCollegeReferrals. A file that silently contained only the
        // 25 rows on screen would be discovered after it had been sent.
        PAGE_SIZE: 25,
        queuePage: 1,
        referralPage: 1,
        selectedApplicant: null,
        
        // Bulk Actions & Clearance State
        selectedRows: [],
        bulkNoShowData: { flagged: [], rejected: [] },
        noShowModalData: { ticket: null },
        referralNoShowModalData: { ticket: null, currentDoj: null, canReschedule: true },
        tempReferralNoShowDoj: null,               
        clearanceAuthModalData: { refId: '' }, 

        // Drawer Temp State (Remarks, Overrides, DMRC Academy)
        actionRemark: '',
        showRemarkInput: false,
        pendingActionType: '', 
        customOverrideFile: null,      // display name only (bound to the UI)
        customOverrideFileObj: null,   // the real File; uploaded at commit time
        tempDmraDate: null,
        
        // Authorization & Issuance State
        issuanceTab: 'Offers',
        // Loaded from /api/signatures/. Every field here is the SERVER's answer,
        // including whether this officer may issue at all -- the browser does
        // not re-derive that from the other fields, so the button and the
        // endpoint can never disagree.
        signatoryDetails: {
            userId: null, name: '', empId: '', designation: '', role: '',
            status: 'None', hasActive: false, hasPending: false,
            activeUrl: null, pendingUrl: null,
            uploadedAt: '', activatedAt: '', reviewedAt: '',
            rejectionReason: '', canIssue: false, canUpload: true
        },
        signatureBusy: false,
        clearanceBlockers: [],
        // The typed value behind "Other" on the intake correction panel.
        intakeCourseOther: '',
        intakeBranchOther: '',
        // The signature chosen but NOT yet sent for approval.
        signatureFileObj: null,
        signatureFileName: '',
        signaturePreviewUrl: null,
        
        // Allowed AHR Joining Dates (Loaded dynamically from TiDB)
        allowedDojDatesByCycle: {},

        // --- COLLEGE REFERRALS (PARALLEL WORKFLOW) STATE ---
        //
        // These records live in their OWN array, not in `applications`. The
        // server keeps them out of /api/hr/queue/ entirely, so they cannot leak
        // into the Verification Queue's tabs, its master search or its exports
        // while they are still being assembled. They appear in `applications`
        // only once merged, at which point they are ordinary applications.
        referralTab: 'Intake Drafts',
        collegeReferrals: [],

        // Reference data for this screen, served by /api/college-referrals/.
        // NOT taken from /api/admin/cycles/ or /api/admin/configs/: both are
        // SYS-ADMIN only, so an HR-OPS or HR-APP user would face an empty cycle
        // list, no selectable joining dates and no sub-departments -- on the
        // very screen they are meant to operate.
        referralCycles: [],
        referralDepartments: [],
        referralSubDeptsByCycle: {},

        newReferralDraft: { cycleId: '', department: '', collegeName: '', studentName: '', mobile: '', email: '', course: '', branch: '', course_other: '', branch_other: '' },
        // Served by /api/me/ so this intake and the Phase-1 referral form can
        // never offer different options for the same field. The values here are
        // only a fallback for the moment before that call returns.
        courseOptions: [],
        branchOptions: [],
        isSavingReferral: false,

        // Mandatory-reason rejection, used from both the Reporting Queue and
        // the no-show dialog.
        referralRejectData: { ticket: null, remark: '', fromNoShow: false },

        // --- SYS-ADMIN (ADMIN CONTROL CENTER) STATE ---
        adminTab: 'iam',
        adminSelectedCycle: '', // Which cycle every admin screen is configuring
        configCycleName: '',    // What the server reported it wrote/read
        pendingConfirm: null,   // Change summary awaiting the administrator's OK
        
        // --- ADMIN MODE STATE ---
        //
        // adminOrigDept and adminOrigWard are GONE. They existed so the
        // browser could adjust the capacity matrix by hand after a god-mode
        // save. The server owns that count now, so the dashboard re-reads it
        // instead of recomputing -- and a snapshot of two fields could never
        // have produced the per-field diff the audit ledger now records.
        adminEditMode: false,
        adminModeStatus: '',
        adminModeRemark: '',

        // Every editable value as it stood when Admin Mode was switched on.
        // The diff is taken against this, so only fields the administrator
        // actually touched are sent. An untouched field is never "corrected"
        // to the value it already had, and never reaches the ledger.
        adminSnapshot: null,
        adminPendingChanges: [],   // readable lines for the dialog
        adminWarnings: null,       // what a reset cannot undo, from the GET
        adminBusy: false,

        // --- FORENSIC & EXPORT STATE ---
        // The Archive Vault's own state now lives together further down, under
        // the ARCHIVE VAULT heading, rather than being split across two places.
        forensicData: { ticket: null, isLoading: false, candidateUploads: [], officialDocuments: [] },
        isExportingQueue: false,
        isExporting: false,
        isExportingAudit: false,

        iamUsers: [], // Now fetches from TiDB
        // Only the code and the role are chosen. Name, designation and
        // department are READ from the employee directory -- see
        // IAMUserAPIView in views.py for why they are never typed here.
        provisionData: { empId: '', role: 'HR-OPS' },
        provisionLookup: {},
        provisionLookupBusy: false,
        provisionLookupError: '',

        adminCycles: [],
        get activeCycles() { return this.adminCycles.filter(c => c.isActive); },

        adminCapacities: [],

        adminDocumentRules: [], // Natively loads from DB

        // The SYS-ADMIN approval queue, loaded from /api/signatures/. Was a
        // hardcoded specimen row that could be approved forever without
        // anything happening.
        pendingSignatures: [],

        // CLEARED MOCK DATA - PREPARED FOR LIVE API
        auditLogs: [],
        auditSearch: '',
        newSubDeptName: '',

        // Mid-Cycle Edits State
        editDatesData: { cycleName: '', start: '', end: '', fpStart: null, fpEnd: null },
        tempQuotas: [],
        tempRules: [],
        newRuleMidCycle: { name: '', isMandatory: true, format: '.pdf,.jpg,.jpeg', isActive: true },
        calendarBuilderData: { dojs: [], fpInstance: null },

        // Wizard State
        wizard: {
            step: 1, term: 'Summer', year: '2027', start: '', end: '',
            capacities: [], subDepts: [], docRules: [], dojs: []
        },
        newWizardRule: { name: '', isMandatory: true, format: '.pdf,.jpg,.jpeg', isActive: true },
        activeCycleNameForWarning: '',

        dbSubDepartments: [], // Natively loads from DB
        
        subDeptSearchQuery: '',
        showSubDeptDropdown: false,

        get filteredSubDepartments() {
            // dbSubDepartments comes from /api/admin/configs/, which only a
            // SYS-ADMIN may read. For HR-OPS and HR-APP it is empty, so fall
            // back to the per-cycle list served with the College Referrals
            // payload. Same source, same administrator configuration -- just
            // reachable by the roles that actually work these queues.
            let active = this.dbSubDepartments.filter(d => d.isActive).map(d => d.name);
            if (active.length === 0 && this.selectedApplicant) {
                active = this.referralSubDeptsByCycle[this.selectedApplicant.cycle] || [];
            }
            if (this.subDeptSearchQuery.trim() === '') return active;
            // Compared in upper case on BOTH sides. This used to uppercase only
            // the QUERY, which worked while every unit was stored in capitals
            // but silently found nothing once real designations arrived --
            // typing "leg" would not match "GM/Legal".
            const q = this.subDeptSearchQuery.toUpperCase();
            return active.filter(d => (d || '').toUpperCase().includes(q));
        },

        get filteredAuditLogs() {
            if (this.auditSearch.trim() === '') return this.auditLogs;
            const query = this.auditSearch.toUpperCase();
            return this.auditLogs.filter(log => log.actor.toUpperCase().includes(query) || log.target.toUpperCase().includes(query) || log.category.toUpperCase().includes(query) || log.details.toUpperCase().includes(query));
        },

        // ======================================================================
        // ARCHIVE VAULT
        //
        // The archive is FILTERED, SORTED AND PAGED ON THE SERVER. A cycle holds
        // hundreds or thousands of records, and the screen used to fetch every
        // one of them -- with its documents, requirements and timeline -- to
        // draw twenty-five rows.
        //
        // So nothing below filters or sorts in the browser. Every control writes
        // to archiveFilters and asks the server again. The consequence worth
        // knowing: `archivedApplications` now holds ONE PAGE, never the cycle,
        // so nothing may derive a total, a dropdown list or a set of dates from
        // it. Those come from the server too -- see archiveOptions.
        // ======================================================================
        archiveFilters: {
            // Everything in an archived cycle is finished, so the useful cuts
            // are outcome and attribute rather than stage. These are built for
            // the archive rather than copied from the Verification Queue: the
            // queue's filters describe where an application is STUCK, and an
            // archived record is not stuck anywhere.
            outcome: '',            // Completed | Rejected
            stage: '',              // how far they actually got -- see below
            department: '',
            subDepartment: '',
            source: '',             // Employee | Institutional
            rejectionCategory: '',
            evaluationResult: '',   // Satisfactory | Unsatisfactory
            emailStatus: '',        // Sent | Pending | Failed
            duration: '',
            doj: '',                // one date, from the calendar
            completedFrom: '',      // a range: completion dates do not cluster
            completedTo: '',
            ward: false,
            waitlisted: false,
            noShow: false,
            resubmitted: false,
            adminEscalated: false,
            dojRescheduleUsed: false,
            offCalendarDoj: false,  // allotted a day never on the calendar
        },

        // HOW FAR THEY GOT. 'Rejected' covers a candidate turned away in week
        // one over a bad photograph AND somebody who served the full internship
        // and failed their assessment. Both are filed identically and they are
        // not the same record.
        archiveStageOptions: [
            { value: 'completed', label: 'Completed' },
            { value: 'failed_evaluation', label: 'Served, failed evaluation' },
            { value: 'joined_not_completed', label: 'Joined, did not complete' },
            { value: 'offered_never_joined', label: 'Offered, never joined' },
            { value: 'rejected_at_verification', label: 'Rejected at verification' },
        ],

        archiveSearch: '',
        archiveYear: '',
        archiveCycle: '',
        archivedApplications: [],
        selectedArchive: null,
        isLoadingArchives: false,
        isLoadingArchiveRecord: false,

        // Its OWN drawer flag. This used to share showFilterDrawer with the
        // Verification Queue, so opening filters on one screen left the panel
        // open on the other.
        showArchiveFilterDrawer: false,

        // Sorted by the dropdown, not by clicking headers -- matching the two
        // live queues. Resolved on the server; blanks sink to the bottom in
        // BOTH directions, which is not what a plain descending sort does.
        archiveSort: { key: 'ticket', dir: 'asc' },
        archiveSortOptions: [
            { value: 'ticket', label: 'Ticket ID' },
            { value: 'name', label: 'Candidate Name' },
            { value: 'college', label: 'College' },
            { value: 'department', label: 'Department' },
            { value: 'submitted', label: 'Submitted' },
            { value: 'doj', label: 'Date of Joining' },
            { value: 'completion', label: 'Date of Completion' },
            { value: 'duration', label: 'Duration' },
        ],

        // Paging. archiveTotal is the count of everything MATCHING, not what is
        // on screen -- the distinction matters for the export, which covers all
        // of it.
        archivePage: 1,
        archivePageCount: 1,
        archiveTotal: 0,
        archiveRangeLabel: '0 of 0',

        // Dropdown values and calendar marks for the selected cycle, from the
        // server. Derived in the browser these would reflect one page: a
        // Department dropdown would list only the departments that happened to
        // appear in the first twenty-five rows.
        archiveOptions: {
            departments: [], subDepartments: [], rejectionCategories: [],
            durations: [], approvedDojDates: [], usedDojDates: [],
            offCalendarDojDates: [],
        },

        // Offered years and cycles come from what has ACTUALLY been archived.
        // These were hardcoded to 2025 and 2026 with both terms assumed, so the
        // pickers listed cycles that had never existed.
        archiveYearsAvailable: [],
        archiveCyclesByYear: {},

        get availableArchiveYears() {
            return this.archiveYearsAvailable;
        },

        get availableArchiveCycles() {
            if (!this.archiveYear) return [];
            return this.archiveCyclesByYear[this.archiveYear] || [];
        },

        // The rows on screen. NOT filtered here -- the server already did.
        get filteredArchives() {
            return this.archivedApplications;
        },

        // How many filters are in force, for the badge on the Filters button.
        // The cycle pickers are not counted: they are how you get to the screen
        // at all, not a narrowing of it.
        get archiveActiveFilterCount() {
            const f = this.archiveFilters;
            let n = 0;
            Object.keys(f).forEach(key => {
                const value = f[key];
                if (value === true) n += 1;
                else if (typeof value === 'string' && value.trim() !== '') n += 1;
            });
            if (this.archiveSearch.trim() !== '') n += 1;
            return n;
        },

        resetArchiveFilters() {
            Object.keys(this.archiveFilters).forEach(key => {
                this.archiveFilters[key] = (this.archiveFilters[key] === true ||
                                            this.archiveFilters[key] === false)
                    ? false : '';
            });
            this.archiveSearch = '';
            this.clearArchiveDojFilter();
            this.archivePage = 1;
            this.fetchArchives();
        },

        // Any filter changing sends the reader back to page 1. Staying on page 6
        // of a list that now has two pages shows an empty table under a pager
        // still claiming page 6 -- the server clamps it, but the reader should
        // not see the jump happen.
        onArchiveFilterChange() {
            this.archivePage = 1;
            this.fetchArchives();
        },

        setArchiveSortKey(key) {
            this.archiveSort.key = key;
            this.archivePage = 1;
            this.fetchArchives();
        },

        toggleArchiveSortDir() {
            this.archiveSort.dir = this.archiveSort.dir === 'asc' ? 'desc' : 'asc';
            this.archivePage = 1;
            this.fetchArchives();
        },

        // The readable name for a stage code, shared by the filter dropdown and
        // the drawer's banner so the two can never disagree.
        archiveStageLabel(value) {
            const match = this.archiveStageOptions.find(s => s.value === value);
            return match ? match.label : '';
        },

        goToArchivePage(page) {
            const target = Math.min(Math.max(1, page), this.archivePageCount);
            if (target === this.archivePage) return;
            this.archivePage = target;
            this.fetchArchives();
        },

        // The same windowed page numbers the two live queues use, so all three
        // pagers behave identically.
        get archivePageNumbers() {
            return this.pageNumbersFor(this.archivePage, this.archivePageCount);
        },

        // Typing searches the whole cycle, so each keystroke is a request. Held
        // back until the typing stops, or a ticket number would fire nine of
        // them and the answers could arrive out of order.
        onArchiveSearchInput() {
            clearTimeout(this._archiveSearchTimer);
            this._archiveSearchTimer = setTimeout(() => {
                this.archivePage = 1;
                this.fetchArchives();
            }, 350);
        },

        // The columns on screen, in order -- the same nine the Verification
        // Queue's "All" tab shows. The export sends this list, so the file
        // always has the same shape as the view it came from.
        get archiveColumns() {
            return [
                { key: 'ticket',       label: 'Ticket ID' },
                { key: 'name',         label: 'Candidate Name' },
                { key: 'status',       label: 'Status' },
                { key: 'ward',         label: 'Ward' },
                { key: 'submitted',    label: 'Submitted' },
                { key: 'department',   label: 'Department' },
                { key: 'referrerName', label: 'Referrer' },
                { key: 'doj',          label: 'Date of Joining' },
            ];
        },

        getCycleDojDates() {
            if (!this.selectedApplicant) return [];
            return this.allowedDojDatesByCycle[this.selectedApplicant.cycle] || [];
        },

        get availableFilterDojDates() {
            let dates = [];
            if (this.filters.cycle) dates = this.allowedDojDatesByCycle[this.filters.cycle] || [];
            else Object.values(this.allowedDojDatesByCycle).forEach(arr => { dates = dates.concat(arr); });
            return [...new Set(dates)].sort();
        },

        // The joining dates an administrator has approved, HIGHLIGHTED in the
        // Target DOJ filter calendar. Narrowed to one cycle once a cycle is
        // chosen; the union of every open cycle's dates before that.
        //
        // Same source as every other calendar in the portal, so a date an
        // administrator adds or withdraws appears here on the next load without
        // anything else being changed.
        get queueApprovedDojDates() {
            return this.availableFilterDojDates;
        },

        // Cycles offered by the Verification Queue's filter. These were two
        // literal strings in the markup -- 'Summer 2026' and 'Winter 2026' --
        // so the filter would have gone on offering two dead cycles and would
        // never have offered a new one.
        //
        // referralCycles comes from /api/college-referrals/, which every
        // dashboard role may read and which returns only cycles still marked
        // active. Archiving a cycle deactivates it, so an archived cycle drops
        // out of this list by itself.
        get queueCycleOptions() {
            return (this.referralCycles || []).map(c => c.name).filter(Boolean);
        },

        // Sub-departments offered by the Verification Queue's filter.
        //
        // This dropdown used to read dbSubDepartments, which comes from
        // /api/admin/configs/ -- a SYS-ADMIN-only endpoint. For HR-OPS and
        // HR-APP, the two roles who actually work this queue, the list was
        // therefore EMPTY and the filter could not be used at all.
        //
        // The per-cycle list every role may read is used instead, narrowed to
        // the chosen cycle when there is one. Anything already recorded against
        // an application is added too, so a unit an administrator has since
        // switched off can still be filtered for on the records that carry it.
        get queueSubDepartmentOptions() {
            const seen = new Set();
            const byCycle = this.referralSubDeptsByCycle || {};

            if (this.filters.cycle) {
                (byCycle[this.filters.cycle] || []).forEach(s => s && seen.add(s));
            } else {
                Object.values(byCycle).forEach(arr => (arr || []).forEach(s => s && seen.add(s)));

                // The administrator list belongs to ONE cycle -- whichever the
                // Admin Control Center is pointed at -- so it is only safe to
                // add while no cycle is being filtered for. Adding it
                // regardless would put another cycle's units into this list.
                (this.dbSubDepartments || []).forEach(d => {
                    if (d && d.isActive && d.name) seen.add(d.name);
                });
            }

            // Units already recorded against an application, so one an
            // administrator has since switched off can still be filtered for.
            // Restricted to the chosen cycle for the same reason as above.
            (this.applications || []).forEach(a => {
                if (!a.subDepartment) return;
                if (this.filters.cycle && a.cycle !== this.filters.cycle) return;
                seen.add(a.subDepartment);
            });

            return [...seen].sort();
        },
        
        masterSearch: '',
        // The College Referrals pipeline has its own search box, so a term
        // typed there does not silently filter the other queue as well.
        referralSearch: '',
        isExportingReferrals: false,
        // The Verification Queue's filters.
        //
        // Removed: dmraStatus (the Academy status is worked in the drawer, not
        // filtered for), hasCustomOverride (it matched offer letters awaiting
        // re-approval, not administrator action, and was not useful), and
        // isCritical, which required BOTH lifeline flags -- neither of which the
        // server ever sets, so it could only ever return nothing.
        //
        // resubmissionType was one dropdown and is now two independent tick
        // boxes, correctionBounce and dojBounce.
        filters: {
            cycle: '', department: '', subDepartment: '', specificDoj: '', evaluationResult: '',
            correctionBounce: false, dojBounce: false,
            isWaitlisted: false, isWard: false, dojRescheduleUsed: false
        },
        sortBy: 'submission_asc',
        fpInstances: [],
        wizardFpInstances: [],

        applications: [],

        // Every request goes through this so the identity header is never
        // forgotten. In production the header is ignored by the server, which
        // reads identity from the intranet session instead.
        authHeaders(extra = {}) {
            const headers = { ...extra };
            // isDevMode is UNKNOWN until /api/me/ answers, and that call needs
            // the header too. Treating "not yet known" as "not dev" meant the
            // very first request of every page load went out with no identity
            // at all, so the server fell back to DEV_DEFAULT_EMPLOYEE_CODE --
            // an ordinary employee with no dashboard account. The whole session
            // then ran as that person: offer letter downloads came back 403,
            // and candidate documents opened UNWATERMARKED, because the default
            // employee happens to be the referrer who submitted them and the
            // viewer correctly treats a referrer as the owner of their own file.
            //
            // It was invisible before only because the default used to be the
            // SYS-ADMIN, who could do everything anyway.
            //
            // Sending the header while the answer is pending is harmless: the
            // intranet provider ignores it entirely, and isDevMode is corrected
            // the moment the response lands.
            if (this.isDevMode !== false) {
                const code = this.devEmployeeCodes[this.currentRole];
                if (code) headers['X-DMRC-Employee'] = code;
            }
            return headers;
        },

        // Dev only: re-resolve identity as the newly selected employee, then
        // reload the queue so the data matches what that role may actually see.
        async switchDevIdentity() {
            const ok = await this.fetchIdentity();
            if (!ok) {
                alert('Could not switch identity. Check that the employee exists in the users table.');
                return;
            }
            await this.fetchLiveQueue();
            await this.fetchAuditLedger();
            // The signature belongs to the identity, so switching identity must
            // reload it. Without this the panel kept showing the previous
            // officer's signature and approval state.
            await this.fetchSignatures();
        },

        async fetchIdentity() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/me/', {
                    headers: this.authHeaders()
                });
                if (!response.ok) {
                    console.error('Identity check failed:', response.status);
                    return false;
                }
                const me = await response.json();
                this.identity = me;
                if (me.academicOptions) {
                    if (Array.isArray(me.academicOptions.courses)) this.courseOptions = me.academicOptions.courses;
                    if (Array.isArray(me.academicOptions.branches)) this.branchOptions = me.academicOptions.branches;
                }
                this.isDevMode = !!me.devMode;
                // Trust the server's answer, not the local default.
                if (me.role) {
                    this.currentRole = me.role;
                    this.roleNames[me.role] = me.fullName || this.roleNames[me.role];
                }
                return true;
            } catch (err) {
                console.error('Identity check failed:', err);
                return false;
            }
        },

        async init() {
            // Resolve who we are BEFORE loading any data, so the very first
            // request already carries the correct identity.
            await this.fetchIdentity();
            // Whether this officer may issue letters at all is a server answer,
            // and the issuance screen needs it before it renders anything.
            await this.fetchSignatures();
            this.$watch('activeTab', () => { this.selectedRows = []; });
            // Back to page one whenever what the queue is showing changes.
            this.$watch('queueViewFingerprint', () => { this.queuePage = 1; });
            this.$watch('referralViewFingerprint', () => { this.referralPage = 1; });
            // Ticket order only means something inside one cycle. If the cycle
            // is cleared while it is active, the sort falls back to Submission
            // (Oldest) rather than silently leaving a meaningless order on
            // screen with the dropdown still claiming to sort by ticket.
            this.$watch('filters.cycle', (name) => {
                if (!name && (this.sortBy === 'ticket_asc' || this.sortBy === 'ticket_desc')) {
                    this.sortBy = 'submission_asc';
                }
                // Which joining dates count as approved depends on the cycle, so
                // the Target DOJ calendar is redrawn to re-mark them. Without
                // this the highlight would keep showing the previous cycle's
                // dates until the calendar happened to rebuild.
                const el = document.getElementById('queueDojFilter');
                if (el && el._flatpickr) el._flatpickr.redraw();
            });
            this.$watch('issuanceTab', () => { this.selectedRows = []; });
            this.$watch('referralTab', () => { this.selectedRows = []; });
            this.$watch('currentRole', async (newRole) => {
                if (newRole !== 'SYS-ADMIN' && this.appView === 'admin_control_center') this.appView = 'verification_queue';
                if (newRole !== 'HR-APP' && this.appView === 'authorization_issuance') this.appView = 'verification_queue';
                this.adminEditMode = false;
                // Becoming a SYS-ADMIN has to LOAD the administrator data.
                // Without this the switcher changed the identity but nothing
                // re-fetched, so the Admin Control Center opened empty -- no
                // cycles, no users, no archives -- and looked broken until the
                // page was reloaded by hand.
                await this.loadAdminData();
            });
            // Every admin screen shows ONE cycle's configuration. Changing the
            // selector reloads it, so what is on screen always belongs to the
            // cycle named in the selector.
            // The archive endpoint returns records only for a NAMED cycle --
            // there may be years of them, so it does not send everything at
            // once. Choosing a cycle therefore has to fetch it. Without this the
            // list stayed empty no matter what was selected: the dropdowns were
            // populated, the filter ran, and it filtered an array that had never
            // been loaded.
            this.$watch('archiveCycle', () => {
                // Back to page one and no filters carried over. A department or
                // a joining date from the previous cycle almost never exists in
                // the next one, so keeping them would show an empty table and
                // look like the cycle had no records in it.
                this.archivePage = 1;
                this.resetArchiveFilters();
            });

            // Changing the YEAR clears the cycle, so the table does not keep
            // showing last year's records under this year's picker.
            this.$watch('archiveYear', () => { this.archiveCycle = ''; });

            this.$watch('adminSelectedCycle', async (name) => {
                if (!name) return;
                await this.fetchAdminConfigs();
                await this.fetchAdminCycles();
            });
            this.$watch('adminEditMode', (val) => {
                if (val && this.selectedApplicant) {
                    this.adminSnapshot = this.captureAdminSnapshot();
                } else {
                    this.adminSnapshot = null;
                    this.adminPendingChanges = [];
                    this.adminWarnings = null;
                }
            });

            // FETCH LIVE DATA FROM TIDB / DJANGO
            await this.fetchLiveQueue();
            
            // FETCH GLOBAL AUDIT LEDGER
            await this.fetchAuditLedger();

            // ADMINISTRATOR DATA -- only when the caller actually is one.
            //
            // These four endpoints are SYS-ADMIN only. They used to be fetched
            // on every load whatever the role, so opening the dashboard as
            // HR-OPS or HR-APP fired four requests that came straight back 403
            // and filled the server log with red. Harmless in itself, but it
            // buries a real error among four expected ones.
            await this.loadAdminData();

            // FETCH COLLEGE REFERRALS + the reference data this screen needs
            await this.fetchCollegeReferrals();

            // COLD STORAGE ARCHIVES -- real applications from closed cycles.
            //
            // This previously held two hardcoded specimen records, displayed in
            // the Archives tab as though they were genuine interns. They had
            // invented names, placeholder Aadhaar text and a college that did
            // not match their university, and they showed up identically on
            // every installation.
            //
            // Loaded by loadAdminData() above, for the same reason.

            // --- RETURNING FROM THE INTAKE FORM ---------------------------
            // Completing a candidate's application opens the Phase-1 form in a
            // second tab. When focus comes back here, the record has changed on
            // the server, so it is re-read.
            //
            // This REPLACES a localStorage handshake in which the two tabs
            // signalled each other and the dashboard matched the returning
            // candidate BY NAME -- which silently picked the wrong record
            // whenever two candidates shared a name, and updated only the
            // browser's copy, so a refresh discarded the change entirely. The
            // server is now the single source of truth.
            window.addEventListener('focus', () => {
                if (this.appView === 'college_referrals') this.fetchCollegeReferrals();
            });
        },
        // --- SIGNATURE AUTHORITY -------------------------------------------
        //
        // One request answers both questions: what is MY signature situation,
        // and (for a SYS-ADMIN) whose signatures are waiting on me.
        async fetchSignatures() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/signatures/', {
                    headers: this.authHeaders()
                });
                if (!response.ok) {
                    // An ordinary employee has no dashboard account and gets a
                    // 401 here. That is expected, not an error worth shouting
                    // about, so the panel simply stays empty.
                    this.pendingSignatures = [];
                    return;
                }
                const data = await response.json();
                if (data.mine) this.signatoryDetails = data.mine;
                this.pendingSignatures = data.pending || [];
            } catch (err) {
                console.error('Signature state failed to load:', err);
            }
        },

        // Choosing a file no longer uploads it. The file is held here and
        // previewed, and nothing is sent until the officer presses "Send for
        // Approval" -- picking a file by accident should not start an approval
        // that a SYS-ADMIN then has to deal with.
        handleSignatureSelect(event) {
            const file = event.target.files[0];
            if (!file) return;

            const allowed = ['image/png', 'image/jpeg'];
            if (!allowed.includes(file.type)) {
                alert('A signature must be a PNG or JPEG image.');
                event.target.value = '';
                return;
            }
            if (file.size > 2 * 1024 * 1024) {
                alert('A signature image must be under 2 MB.');
                event.target.value = '';
                return;
            }

            this.signatureFileObj = file;
            this.signatureFileName = file.name;
            // Shown straight from the browser, so the officer sees what they
            // picked before committing to it. Released in clearSignatureSelection().
            if (this.signaturePreviewUrl) URL.revokeObjectURL(this.signaturePreviewUrl);
            this.signaturePreviewUrl = URL.createObjectURL(file);
        },

        clearSignatureSelection() {
            if (this.signaturePreviewUrl) URL.revokeObjectURL(this.signaturePreviewUrl);
            this.signatureFileObj = null;
            this.signatureFileName = '';
            this.signaturePreviewUrl = null;
            const input = document.getElementById('sigUploadInput');
            if (input) input.value = '';
        },

        // Sends the chosen file for approval. It does NOT take effect here --
        // it waits for a SYS-ADMIN, and the officer's existing signature keeps
        // working in the meantime.
        async submitSignatureForApproval() {
            if (!this.signatureFileObj) return;

            const form = new FormData();
            form.append('file', this.signatureFileObj);
            this.signatureBusy = true;
            try {
                const response = await fetch('http://127.0.0.1:8000/api/signatures/', {
                    method: 'POST',
                    headers: this.authHeaders(),   // no Content-Type: the browser sets the multipart boundary
                    body: form
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.error || 'The signature could not be sent for approval.');
                    return;
                }
                if (data.signature) this.signatoryDetails = data.signature;
                this.clearSignatureSelection();
                alert(data.message);
            } catch (err) {
                console.error('Signature upload failed:', err);
                alert('The signature could not be sent: the server could not be reached.');
            } finally {
                this.signatureBusy = false;
                await this.fetchSignatures();
                this.fetchAuditLedger();
            }
        },

        async decideSignature(sig, decision, reason) {
            this.signatureBusy = true;
            try {
                const response = await fetch('http://127.0.0.1:8000/api/signatures/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ userId: sig.userId, decision, reason: reason || '' })
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.error || 'The decision could not be recorded.');
                    return;
                }
                alert(data.message);
            } catch (err) {
                console.error('Signature decision failed:', err);
                alert('The decision could not be recorded: the server could not be reached.');
            } finally {
                this.signatureBusy = false;
                await this.fetchSignatures();
                this.fetchAuditLedger();
            }
        },

        async fetchLiveQueue() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/hr/queue/', { headers: this.authHeaders() });
                if (response.ok) {
                    this.applications = await response.json();
                } else {
                    console.error("Failed to load HR Omni-Queue from Django.");
                }
            } catch (error) {
                console.error("Network error fetching live queue:", error);
            }
        },

        // Cold Storage. SYS-ADMIN only, and read entirely from the archive
        // tables -- a closed cycle's records no longer exist in the live ones.
        // The four SYS-ADMIN-only datasets, fetched together and only when the
        // current identity may actually read them.
        //
        // Silent when the role is wrong: this is called on every load and on
        // every role change, so a message would fire constantly for HR-OPS,
        // who is not missing anything they are entitled to.
        async loadAdminData() {
            if (this.currentRole !== 'SYS-ADMIN') return;
            await this.fetchIAMUsers();
            await this.fetchAdminCycles();
            await this.fetchAdminConfigs();
            await this.fetchArchives();
        },

        // Sends the filters, the sort and the page; receives one page of rows.
        //
        // Every archive control funnels through here. Nothing is filtered or
        // sorted in the browser any more, because the browser no longer holds
        // the cycle -- only the page it is showing.
        async fetchArchives() {
            this.isLoadingArchives = true;
            try {
                const params = new URLSearchParams();
                if (this.archiveCycle) {
                    // 'Summer 2026' -> term=Summer, year=2026. Split on the LAST
                    // space, so a term that ever contains one still parses.
                    const at = this.archiveCycle.lastIndexOf(' ');
                    params.set('term', this.archiveCycle.slice(0, at));
                    params.set('year', this.archiveCycle.slice(at + 1));
                } else if (this.archiveYear) {
                    params.set('year', this.archiveYear);
                }

                const f = this.archiveFilters;
                Object.keys(f).forEach(key => {
                    const value = f[key];
                    // Only what is actually set. Sending empty values would make
                    // the request unreadable in a log for no benefit.
                    if (value === true) params.set(key, 'true');
                    else if (typeof value === 'string' && value.trim() !== '') {
                        params.set(key, value.trim());
                    }
                });

                if (this.archiveSearch.trim() !== '') {
                    params.set('search', this.archiveSearch.trim());
                }
                params.set('sortKey', this.archiveSort.key);
                params.set('sortDir', this.archiveSort.dir);
                params.set('page', this.archivePage);

                const response = await fetch(
                    `${API_BASE}/api/hr/archives/?${params.toString()}`,
                    { headers: this.authHeaders() });

                if (!response.ok) {
                    if (response.status !== 403) console.error("GET Archives failed:", response.status);
                    this.archivedApplications = [];
                    this.archiveTotal = 0;
                    this.archivePageCount = 1;
                    this.archiveRangeLabel = '0 of 0';
                    return;
                }
                const data = await response.json();
                this.archivedApplications = data.records || [];
                this.archiveYearsAvailable = data.availableYears || [];
                this.archiveCyclesByYear = data.cyclesByYear || {};
                this.archiveTotal = data.total || 0;
                this.archivePageCount = data.pageCount || 1;
                // Taken from the RESPONSE, not kept locally: the server clamps a
                // page past the end, and the pager must show where the reader
                // actually landed rather than where they asked to go.
                this.archivePage = data.page || 1;
                this.archiveRangeLabel = data.rangeLabel || '0 of 0';
                if (data.options) {
                    this.archiveOptions = Object.assign(
                        { departments: [], subDepartments: [], rejectionCategories: [],
                          durations: [], approvedDojDates: [], usedDojDates: [],
                          offCalendarDojDates: [] },
                        data.options);
                    // The calendar marks days from these lists, so it has to be
                    // rebuilt whenever they change -- switching cycles brings a
                    // different set of approved dates.
                    this.$nextTick(() => this.initArchiveDojCalendar(
                        document.getElementById('archiveDojFilter')));
                }
            } catch (error) {
                console.error("Network error fetching Archives:", error);
                // Left empty rather than falling back to specimen data: an
                // empty vault is honest, invented records are not.
                this.archivedApplications = [];
                this.archiveTotal = 0;
                this.archivePageCount = 1;
                this.archiveRangeLabel = '0 of 0';
            } finally {
                this.isLoadingArchives = false;
            }
        },

        // Opens ONE archived candidate in the SAME drawer a live application
        // uses, rather than a second drawer built to resemble it.
        //
        // Two drawers showing the same record in two shapes drift apart, and
        // the archive's copy had already fallen behind -- it showed nothing of
        // the clearance or the certificate.
        //
        // This costs a request, because the table's rows carry nine columns and
        // the drawer needs sixty fields, the documents, the requirements and the
        // timeline. Fetching all that for every row on the chance one is opened
        // is what made this screen unusable at a full cycle's size.
        async openArchivedRecord(ticket) {
            this.isLoadingArchiveRecord = true;
            try {
                const response = await fetch(
                    `${API_BASE}/api/hr/archives/record/?ticket=${encodeURIComponent(ticket)}`,
                    { headers: this.authHeaders() });

                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    alert(data.error || 'That record could not be opened. Reload the archive and try again.');
                    return;
                }

                const record = await response.json();
                // isArchivedRecord arrives set from the server. It is the ONE
                // flag the drawer reads to disable every action, so it is not
                // recomputed here -- a second source for it is a second place
                // for it to be wrong.
                this.selectedApplicant = record;
                this.selectedArchive = record;

                // ADMIN EDIT MODE IS FORCED OFF.
                //
                // It is application-level state, not per-record. A SYS-ADMIN who
                // turned it on to correct a live application and then opened an
                // archived one would find the identity fields editable, because
                // every one of them is bound to :disabled="!adminEditMode".
                // Nothing could actually be saved -- the Save controls sit
                // inside the read-only guard -- but a closed record that looks
                // editable is a closed record somebody will try to edit.
                this.adminEditMode = false;

                // Left-over state from whatever was open before. The sub-
                // department box in particular keeps its own search text, which
                // would otherwise show the previous candidate's unit.
                this.subDeptSearchQuery = record.subDepartment || '';
                this.showSubDeptDropdown = false;

                new bootstrap.Offcanvas(document.getElementById('applicantDrawer')).show();
            } catch (error) {
                console.error("Network error opening archived record:", error);
                alert('That record could not be opened. Check the connection and try again.');
            } finally {
                this.isLoadingArchiveRecord = false;
            }
        },

        // --- THE ARCHIVE'S JOINING-DATE CALENDAR -----------------------------
        //
        // The same widget used everywhere else in the portal, marking THREE
        // kinds of day rather than one:
        //
        //   approved and used        a normal intake date
        //   approved, never used     offered, nobody was allotted it
        //   used but NEVER approved  an exception was made for that candidate
        //
        // The third is the one worth having. HR may allot ANY date when
        // scheduling, and once a cycle is closed this is the only place that
        // decision is visible.
        //
        // Every date stays selectable, including unapproved and past ones. The
        // marks say where the records are; they do not limit the choice.
        initArchiveDojCalendar(element) {
            if (!element) return;
            if (element._flatpickr) element._flatpickr.destroy();
            const fp = flatpickr(element, {
                dateFormat: 'Y-m-d', altInput: true, altFormat: 'd-m-Y',
                allowInput: false,
                defaultDate: this.archiveFilters.doj || null,
                onDayCreate: (dObj, dStr, fpObj, dayElem) => {
                    const y = dayElem.dateObj.getFullYear();
                    const m = String(dayElem.dateObj.getMonth() + 1).padStart(2, '0');
                    const d = String(dayElem.dateObj.getDate()).padStart(2, '0');
                    const iso = `${y}-${m}-${d}`;
                    const options = this.archiveOptions;
                    const approved = (options.approvedDojDates || []).includes(iso);
                    const used = (options.usedDojDates || []).includes(iso);
                    if (approved && used) dayElem.classList.add('ahr-approved-date');
                    else if (approved) dayElem.classList.add('ahr-approved-unused-date');
                    else if (used) dayElem.classList.add('ahr-offcalendar-date');
                },
                onChange: (dates, str) => {
                    this.archiveFilters.doj = str || '';
                    this.onArchiveFilterChange();
                }
            });
            this.fpInstances.push(fp);
        },

        clearArchiveDojFilter() {
            this.archiveFilters.doj = '';
            const el = document.getElementById('archiveDojFilter');
            if (el && el._flatpickr) el._flatpickr.clear();
        },


        async fetchCollegeReferrals() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/college-referrals/', { headers: this.authHeaders() });
                if (!response.ok) {
                    console.error("GET College Referrals failed with status:", response.status);
                    return;
                }
                const data = await response.json();
                this.collegeReferrals = data.records || [];
                this.referralCycles = data.cycles || [];
                this.referralDepartments = data.departments || [];
                this.referralSubDeptsByCycle = data.subDepartmentsByCycle || {};

                // Fill in any joining dates the admin endpoint could not supply.
                // Existing entries win, so a SYS-ADMIN's richer payload is never
                // overwritten by this one.
                this.allowedDojDatesByCycle = {
                    ...(data.allowedDojDatesByCycle || {}),
                    ...this.allowedDojDatesByCycle
                };
            } catch (error) {
                console.error("Network error fetching College Referrals:", error);
            }
        },

        // Every College Referrals action goes through here, so the request
        // shape, the error handling and the refresh afterwards are identical
        // across all of them. Returns the parsed body on success, or null --
        // callers MUST check, and must not advance the record on null.
        async syncReferralAction(payload) {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/college-referrals/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify(payload)
                });
                const data = await response.json().catch(() => ({}));

                if (!response.ok) {
                    // A refused merge lists exactly what is missing. Showing that
                    // list is the whole point: a disabled button with no
                    // explanation leaves HR guessing.
                    let message = data.error || 'The action could not be completed.';
                    if (Array.isArray(data.missing) && data.missing.length) {
                        message += '\n\nStill required:\n  \u2022 ' + data.missing.join('\n  \u2022 ');
                    }
                    alert(message);
                    return null;
                }

                await this.fetchCollegeReferrals();
                await this.fetchAuditLedger();
                return data;
            } catch (error) {
                console.error("College Referral action failed:", error);
                alert('The server could not be reached. Nothing has been changed.');
                return null;
            }
        },

        closeApplicantDrawer() {
            const drawer = bootstrap.Offcanvas.getInstance(document.getElementById('applicantDrawer'));
            if (drawer) drawer.hide();
        },

        async fetchAuditLedger() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/audit-ledger/', { headers: this.authHeaders() });
                if (response.ok) {
                    const data = await response.json();
                    this.auditLogs = data.map(log => ({
                        logId: log.logId,
                        timestamp: log.timestamp,
                        actor: `${log.actor} [${log.role}]`,
                        category: log.action, 
                        target: log.ticketId, // Properly structured by backend now
                        details: log.remark
                    }));
                } else {
                    console.error("Failed to load Audit Ledger from Django.");
                }
            } catch (error) {
                console.error("Network error fetching Audit Ledger:", error);
            }
        },

        async syncActionToCloud(payload) {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/hr/action/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify(payload)
                });
                if (!response.ok) {
                    const detail = await response.text();
                    console.error("Backend rejection:", detail);
                    // Surface refusals the user must act on -- notably the
                    // one-time no-show lifeline -- rather than failing silently
                    // while the UI pretends the action succeeded.
                    try {
                        const parsed = JSON.parse(detail);
                        if (parsed.error) alert(parsed.error);
                    } catch (e) { /* non-JSON error body: console is enough */ }
                    await this.fetchLiveQueue();   // resync: local state may be wrong
                } else {
                    this.fetchAuditLedger();
                    // Refresh the queue and re-point the open drawer at the updated
                    // record. Without this the drawer keeps the copy it was opened
                    // with, so a status change never appears on its timeline until
                    // the drawer is closed and reopened.
                    const openTicket = this.selectedApplicant ? this.selectedApplicant.ticket : null;
                    await this.fetchLiveQueue();
                    if (openTicket) {
                        const refreshed = this.applications.find(a => a.ticket === openTicket);
                        if (refreshed) this.selectedApplicant = refreshed;
                    }
                }
            } catch (err) {
                console.error("Cloud sync failed:", err);
            }
        },

        // --- NEW DOJ STATE MACHINE HELPERS ---
        getDisplayDojLabel(status) {
            if (['Scheduled', 'Pending Offer Letter', 'Fix Joining', 'Offer Ready', 'Pending Offer Re-Approval', 'Pending Arrival', 'Ready for Merge'].includes(status)) return 'Allotted DOJ';
            if (['Joined', 'Fix Clearance', 'Pending Certificate', 'Pending Dispatch', 'Completed'].includes(status)) return 'Actual DOJ';
            return 'Requested DOJ';
        },
        // THE joining date that matters for one record, chosen by its status.
        // The column, the Target DOJ filter, the Date of Joining sort and the
        // projected end date all read this one function, so they can never
        // disagree about which of the three stored dates a candidate's joining
        // date actually is.
        //
        // 'Approved' sits in the allotted group even though a date is usually
        // allotted a moment later: the server already falls back to the
        // requested date while nothing has been allotted, so this reads
        // correctly either way and starts reading the real date the instant one
        // exists.
        getDisplayDojValue(app) {
            if (!app) return '';
            if (['Approved', 'Scheduled', 'Pending Offer Letter', 'Fix Joining', 'Offer Ready', 'Pending Offer Re-Approval', 'Pending Arrival', 'Ready for Merge'].includes(app.status)) return app.allottedDoj;
            if (['Joined', 'Fix Clearance', 'Pending Certificate', 'Pending Dispatch', 'Completed'].includes(app.status)) return app.actualDoj;
            return app.doj;
        },
        getTabDojHeader(tab) {
            if (['All', 'Resubmissions', 'Rejected'].includes(tab)) return 'Date of Joining';
            if (['Scheduled', 'Pending Offer Letter', 'Fix Joining', 'Ready for Handover'].includes(tab)) return 'Allotted DOJ';
            if (['Active', 'Fix Clearance', 'Pending Certificate', 'Completed'].includes(tab)) return 'Actual DOJ';
            return 'Requested DOJ'; 
        },

        // Which filters were in force, as a short readable phrase for the audit
        // ledger. 'No filters' rather than an empty string, so a ledger entry
        // never leaves a reader wondering whether the field failed to record.
        activeFilterSummary() {
            const f = this.filters;
            const parts = [];
            if (f.cycle) parts.push(`cycle ${f.cycle}`);
            if (f.department) parts.push(`department ${f.department}`);
            if (f.subDepartment) parts.push(`sub-department ${f.subDepartment}`);
            if (f.specificDoj) parts.push(`DOJ ${f.specificDoj}`);
            if (f.evaluationResult) parts.push(`evaluation ${f.evaluationResult}`);
            if (f.correctionBounce) parts.push('returned for corrections');
            if (f.dojBounce) parts.push('returned for DOJ update');
            if (f.isWaitlisted) parts.push('waitlisted');
            if (f.isWard) parts.push('wards');
            if (f.dojRescheduleUsed) parts.push('DOJ reschedule used');
            if (this.masterSearch) parts.push(`search "${this.masterSearch}"`);
            return parts.length ? parts.join(', ') : 'No filters';
        },

        // --- UNIVERSAL WYSIWYG EXPORT ENGINE ---
        async executeExport(moduleType, format) {
            let payloadIds = [];
            let fileName = `DMRC_Export_${moduleType}_${new Date().toISOString().split('T')[0]}`;

            // Context carried to the server: what the file is OF, and what the
            // officer could see when they asked for it. Recorded in the audit
            // ledger, and for the queue it also names the joining-date column.
            let context = {};

            // Extract precisely filtered IDs based on the active screen context
            if (moduleType === 'queue') {
                this.isExportingQueue = true;
                // The FULL filtered list, never the page on screen. Paging is a
                // drawing limit; a file that silently held only 25 rows would be
                // discovered after it had been sent to somebody.
                payloadIds = this.processedQueue.map(app => app.ticket);
                const cycleStr = this.filters.cycle ? `_${this.filters.cycle.replace(/\s+/g, '')}` : '';
                fileName = `DMRC_Active_Queue_${this.activeTab.replace(/\s+/g, '')}${cycleStr}_${new Date().toISOString().split('T')[0]}`;
                context = {
                    tab: this.activeTab,
                    // The exact heading on screen, so the column in the file
                    // cannot say 'Actual DOJ' while holding requested dates.
                    dojHeader: this.getTabDojHeader(this.activeTab),
                    filters: this.activeFilterSummary(),
                    sort: this.sortBy
                };
            } else if (moduleType === 'archive') {
                this.isExporting = true;
                // NO LIST OF TICKETS. The archive is paged, so the visible list
                // is twenty-five records; sending it would have produced a
                // twenty-five row file that only revealed itself as incomplete
                // after somebody had sent it on. The server re-runs the filters
                // and exports everything they match.
                payloadIds = [];

                // The filename reads the ARCHIVE'S OWN department filter. It
                // used to read this.filters.department -- the VERIFICATION
                // QUEUE's filter -- so an archive export was named after
                // whatever department happened to be selected on a different
                // screen, and read '_AllDepts' when the archive's own
                // department filter WAS set.
                const af = this.archiveFilters;
                let deptStr = af.department ? `_${af.department}` : '_AllDepts';
                fileName = `DMRC_Archive_${this.archiveCycle.replace(/ /g, '')}${deptStr}`;

                // What the audit ledger records. It used to read 'No filters'
                // unless a search had been typed, however many of the others
                // were set -- so the ledger misdescribed what had been taken
                // out of the vault.
                const applied = [];
                Object.keys(af).forEach(key => {
                    const value = af[key];
                    if (value === true) applied.push(key);
                    else if (typeof value === 'string' && value.trim() !== '') {
                        applied.push(`${key}=${value.trim()}`);
                    }
                });
                if (this.archiveSearch.trim() !== '') {
                    applied.push(`search=${this.archiveSearch.trim()}`);
                }
                context = { tab: this.archiveCycle || 'Archive',
                            filters: applied.length ? applied.join(', ') : 'No filters' };
            } else if (moduleType === 'college') {
                this.isExportingReferrals = true;
                payloadIds = this.filteredCollegeReferrals.map(a => a.ticket);
                fileName = `DMRC_College_Referrals_${this.referralTab.replace(/\s+/g, '')}_${new Date().toISOString().split('T')[0]}`;
                context = {
                    tab: this.referralTab,
                    filters: this.referralSearch ? `search "${this.referralSearch}"` : 'No filters'
                };
            } else if (moduleType === 'audit') {
                this.isExportingAudit = true;
                payloadIds = this.filteredAuditLogs.map(log => log.logId);
                fileName = `DMRC_Audit_Ledger_${new Date().toISOString().split('T')[0]}`;
                context = { tab: 'Audit Ledger', filters: this.auditSearch ? `search "${this.auditSearch}"` : 'No filters' };
            }

            try {
                const response = await fetch('http://127.0.0.1:8000/api/admin/export/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        module: moduleType,
                        format: format,
                        // Sent in the order shown on screen, so any sort the
                        // administrator applied survives into the file.
                        ids: payloadIds,
                        // The columns currently displayed. The server looks the
                        // VALUES up from the archive rather than taking them
                        // from this page: a view left open for an hour would
                        // otherwise be exported verbatim into a document DMRC
                        // may keep as a record.
                        columns: moduleType === 'archive' ? this.archiveColumns : undefined,
                        // THE ARCHIVE SENDS FILTERS, NOT RECORDS. It is the one
                        // paged module, so the server resolves what to export
                        // rather than being handed the page on screen. The cycle
                        // travels with them: the archive is keyed by term and
                        // year, never by cycle id.
                        filters: moduleType === 'archive' ? (() => {
                            const at = this.archiveCycle.lastIndexOf(' ');
                            return Object.assign({}, this.archiveFilters, {
                                term: this.archiveCycle.slice(0, at),
                                year: this.archiveCycle.slice(at + 1),
                                search: this.archiveSearch.trim(),
                                sortKey: this.archiveSort.key,
                                sortDir: this.archiveSort.dir,
                            });
                        })() : undefined,
                        context: context
                    })
                });

                if (!response.ok) throw new Error("Failed to generate export file from server.");

                // Dynamically force download of the generated file block
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${fileName}.${format === 'excel' ? 'xlsx' : 'pdf'}`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);

                // The ledger entry is written BY THE SERVER, inside the same
                // request that produced the file. This used to push a row into
                // this page's own list instead: it never reached the database,
                // so it disappeared on refresh and no entry existed for anyone
                // reviewing who had taken data out of the portal.
                //
                // Refreshed here so the new entry appears without a reload.
                this.fetchAuditLedger();

            } catch (error) {
                alert(`Export Error: ${error.message}`);
            } finally {
                if (moduleType === 'queue') this.isExportingQueue = false;
                if (moduleType === 'archive') this.isExporting = false;
                if (moduleType === 'audit') this.isExportingAudit = false;
                if (moduleType === 'college') this.isExportingReferrals = false;
            }
        },

        exportQueue(format) {
            if (this.processedQueue.length === 0) { alert("No records in current view to export."); return; }
            this.executeExport('queue', format);
        },

        exportArchive(format) {
            // Checked against the TOTAL matching the filters, not the rows on
            // screen. Those are the same thing on page one of a small result
            // and different on every other page.
            if (!this.archiveCycle || this.archiveTotal === 0) {
                alert("No records in current view to export.");
                return;
            }
            this.executeExport('archive', format);
        },

        // The College Referrals pipeline, exported with the columns it SHOWS --
        // college, university, course and branch, which the Verification Queue
        // does not display and an institutional record is largely about.
        exportCollegeReferrals(format) {
            const rows = this.filteredCollegeReferrals;
            if (!rows.length) { alert('No records in the current view to export.'); return; }
            this.executeExport('college', format);
        },

        exportAuditLog(format) {
            if (this.filteredAuditLogs.length === 0) { alert("No records in current view to export."); return; }
            this.executeExport('audit', format);
        },

        // --- HR-OPS DIRECT APPROVAL (FRICTIONLESS) ---
        async executeDirectApproval() {
            if (!this.selectedApplicant) return;
            this.selectedApplicant.status = 'Approved';
            
            // FIRE TO TI-DB CLOUD
            await this.syncActionToCloud({
                ticket: this.selectedApplicant.ticket,
                status: 'Approved',
                remark: 'Direct HR-OPS Validation'
            });

            alert(`[AUDIT LOG] System Event:\nActor: ${this.roleNames[this.currentRole]} [${this.currentRole}]\nAction: Approved & Routed to Logistics Assignment.`);
            let offcanvas = bootstrap.Offcanvas.getInstance(document.getElementById('applicantDrawer'));
            if(offcanvas) offcanvas.hide();
        },
        
        async executeBulkDirectApproval() {
            if (this.selectedRows.length === 0) return;
            alert(`[AUDIT LOG] Mass Approval executed on ${this.selectedRows.length} candidates.`);
            for (let t of this.selectedRows) {
                let app = this.applications.find(a => a.ticket === t);
                if(app) { 
                    app.status = 'Approved'; 
                    await this.syncActionToCloud({
                        ticket: app.ticket,
                        status: 'Approved',
                        remark: 'Mass HR-OPS Validation'
                    });
                }
            }
            this.selectedRows = [];
        },

        // --- HR-OPS FINAL CLEARANCE AUTHENTICATION (NEW GATE) ---
        // Checks with the SERVER before asking for the file number.
        //
        // Nothing is more annoying than typing an official reference into a
        // dialog only to be told afterwards that Annexure B is missing. So the
        // outstanding list is fetched first and shown plainly, and the dialog
        // only opens when there is genuinely nothing left to do.
        async triggerClearanceAuth() {
            if (!this.selectedApplicant) return;

            if (this.selectedApplicant.evaluationResult !== 'Unsatisfactory') {
                const saved = await this.saveClearance();
                const blockers = (saved && saved.blockers) || [];
                if (blockers.length) {
                    alert('Clearance is not complete yet. Still outstanding:\n\n  '
                          + blockers.join('\n  '));
                    return;
                }
            }

            this.clearanceAuthModalData.refId = '';
            new bootstrap.Modal(document.getElementById('clearanceAuthModal')).show();
        },

        // Submit for Final Review, or reject on an Unsatisfactory evaluation.
        //
        // The file number is mandatory for BOTH -- a rejection is itself an
        // official act against a physical approval. It is not asked for again
        // on a resubmission after HR-APP returned the application: it is the
        // same approval, and re-typing it would only be a chance to mistype it.
        async executeClearance() {
            const refId = (this.clearanceAuthModalData.refId || '').trim();
            const a = this.selectedApplicant;
            if (!a) return;

            const unsatisfactory = a.evaluationResult === 'Unsatisfactory';
            const resubmission = a.status === 'Fix Clearance';

            if (!refId && !resubmission) {
                alert('A file number is required. It is the reference for the physical approval covering this clearance.');
                return;
            }
            if (unsatisfactory && !confirm(
                `Reject ${a.ticket}?\n\nThe mentor marked this internship Unsatisfactory, so no completion `
              + `certificate will be issued. Everything recorded so far is kept.`)) return;

            // Save whatever is on screen first, so nothing typed but not yet
            // saved is lost by the submission.
            await this.saveClearance();

            try {
                const response = await fetch('http://127.0.0.1:8000/api/clearance/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ ticket: a.ticket, fileNumber: refId,
                                           decision: unsatisfactory ? 'reject' : 'submit' })
                });
                const data = await response.json();
                if (!response.ok) {
                    let message = data.error || 'The clearance could not be submitted.';
                    if (data.blockers && data.blockers.length) {
                        message = 'Still outstanding:\n  ' + data.blockers.join('\n  ');
                    }
                    alert(message);
                    return;
                }
                alert(data.message);
                const modal = bootstrap.Modal.getInstance(document.getElementById('clearanceAuthModal'));
                if (modal) modal.hide();
                this.closeDrawer();
            } catch (err) {
                console.error('Clearance submission failed:', err);
                alert('The clearance could not be submitted: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },


        // --- FILE UPLOAD CLEARANCE HELPER ---
        clearFileUpload(stateKey, inputId) {
            let idx = this.selectedApplicant ? this.applications.findIndex(a => a.ticket === this.selectedApplicant.ticket) : -1;
            
            if (stateKey === 'signature') {
                this.signatoryDetails.pendingSignature = null;
                this.signatoryDetails.approvalStatus = 'None';
            } else if (stateKey === 'customOverride') {
                this.customOverrideFile = null;
                this.customOverrideFileObj = null;
                if (idx !== -1) this.applications[idx].customOverrideFile = null;
            } else if (stateKey === 'annexureB' && idx !== -1) {
                this.applications[idx].annexureBFile = null;
            } else if (stateKey === 'dmraExemption' && idx !== -1) {
                this.applications[idx].dmraExemptionFile = null;
            }
            
            if (idx !== -1) this.selectedApplicant = this.applications[idx];
            
            const fileInput = document.getElementById(inputId);
            if (fileInput) {
                fileInput.value = '';
            }
        },

        // --- DMRC ACADEMY LOGISTICS HANDLERS ---
        initDmraCalendar(element) {
            if (!element) return;
            if (element._flatpickr) element._flatpickr.destroy();
            let fp = flatpickr(element, {
                dateFormat: 'Y-m-d', altInput: true, altFormat: 'd-m-Y', minDate: 'today',
                defaultDate: this.selectedApplicant ? this.selectedApplicant.dmraSessionDate : null,
                onChange: (selectedDates, str) => { this.tempDmraDate = str; }
            });
            this.fpInstances.push(fp);
        },

        // Schedules the DMRA session on the SERVER, which locks it.
        //
        // This used to set the date locally and announce "Auto-email dispatched
        // to intern" in an alert. No email exists, and the date was never
        // locked -- it could be changed on the next page load.
        async scheduleDmraSession() {
            if (!this.tempDmraDate || !this.selectedApplicant) return;
            if (!confirm(`Schedule the DMRA Academy session for ${this.formatDate(this.tempDmraDate)}?\n\n`
                       + `This date CANNOT be changed afterwards. The candidate is told it, and only a `
                       + `system administrator can correct it.`)) return;
            try {
                const response = await fetch('http://127.0.0.1:8000/api/dmra-session/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ ticket: this.selectedApplicant.ticket,
                                           sessionDate: this.tempDmraDate })
                });
                const data = await response.json();
                if (!response.ok) { alert(data.error || 'The session could not be scheduled.'); return; }
                alert(data.message
                      + '\n\nThe email to the candidate will go out once the mail system is built.');
                this.tempDmraDate = null;
            } catch (err) {
                console.error('DMRA scheduling failed:', err);
                alert('The session could not be scheduled: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },

        // Saves clearance progress as it arrives. Called whenever a field in the
        // clearance panel changes, so nothing is lost if HR-OPS closes the
        // drawer halfway -- the evaluation comes from a mentor, Annexure B is
        // chased, and the two rarely arrive on the same day.
        async saveClearance(extra = {}) {
            if (!this.selectedApplicant) return null;
            const a = this.selectedApplicant;
            try {
                const response = await fetch('http://127.0.0.1:8000/api/clearance/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify(Object.assign({
                        ticket: a.ticket,
                        evaluationResult: a.evaluationResult || '',
                        evaluationRemarks: a.evaluationRemark || '',
                        attendanceVerified: !!a.attendanceCleared,
                        reportVerified: !!a.reportCleared,
                        projectTitle: a.universalTextField || '',
                        dmraAttended: a.dmraAttended === undefined || a.dmraAttended === null
                                      ? null : a.dmraAttended === 'true'
                    }, extra))
                });
                const data = await response.json();
                if (!response.ok) { alert(data.error || 'Clearance could not be saved.'); return null; }
                // Written onto the OPEN APPLICATION, which is what the button
                // and the "Still outstanding" list actually read. It used to be
                // stored in a separate top-level variable that nothing was
                // bound to, so the list kept showing whatever was outstanding
                // when the page loaded and the button never unlocked however
                // much HR-OPS filled in.
                if (this.selectedApplicant) this.selectedApplicant.clearanceBlockers = data.blockers || [];
                this.clearanceBlockers = data.blockers || [];
                return data;
            } catch (err) {
                console.error('Clearance save failed:', err);
                return null;
            }
        },


        // --- NO-SHOW BIFURCATED WORKFLOW ---
        triggerNoShow(ticketId) {
            this.noShowModalData.ticket = ticketId;
            new bootstrap.Modal(document.getElementById('noShowEscalationModal')).show();
        },

        async executeNoShow(route) {
            // The lifeline is spent: this is an outright rejection, not a
            // return. The server refuses a second referrer bounce anyway, so
            // offering one would only produce an error.
            if (route === 'reject') {
                if (!confirm('Reject this application?\n\nThe candidate has already had one rescheduled '
                           + 'joining date and failed to report again. This closes the application.')) return;
                await this.syncActionToCloud({
                    ticket: this.selectedApplicant.ticket,
                    status: 'Rejected',
                    bounceCategory: 'No Show',
                    remark: 'NO-SHOW LIFELINE EXHAUSTED. APPLICATION CLOSED.',
                    isAdminEscalated: false,
                    lifelineExhausted: true
                });
                const modal = bootstrap.Modal.getInstance(document.getElementById('noShowEscalationModal'));
                if (modal) modal.hide();
                this.closeDrawer();
                await this.refreshAfterAction();
                return;
            }
            return this._routeNoShow(route);
        },

        async _routeNoShow(route) {
            let logMsg = `[AUDIT LOG] System Event:\nActor: ${this.roleNames[this.currentRole]} [${this.currentRole}]\nTarget: ${this.noShowModalData.ticket}\nAction: No-Show Processed\nRoute: ${route === 'admin' ? 'Sent to Admin (Stealth Override)' : 'Returned to Referrer'}`;
            if(this.selectedApplicant) {
                this.selectedApplicant.status = 'Rejected';
                if(route === 'admin') this.selectedApplicant.isAdminEscalated = true;
                
                // FIRE TO TI-DB CLOUD
                await this.syncActionToCloud({
                    ticket: this.selectedApplicant.ticket,
                    status: 'Rejected',
                    // Only the referrer route is a bounce. An admin escalation is
                    // a stealth hold and must NOT become actionable for the referrer.
                    // The category is sent for BOTH routes: an escalated no-show
                    // is still a no-show rejection and must be filed as one, or
                    // it disappears from the Rejected tab. What differs is
                    // whether the REFERRER is asked to act, which the server
                    // derives from isAdminEscalated.
                    bounceCategory: 'No Show',
                    remark: route === 'admin' ? 'Stealth Escalation to Admin' : 'Returned to Referrer',
                    isAdminEscalated: route === 'admin'
                });
                if (route !== 'admin') {
                    this.selectedApplicant.awaitingReferrerAction = true;
                    this.selectedApplicant.rejectionCategory = 'No Show';
                }
            }
            alert(logMsg);
            bootstrap.Modal.getInstance(document.getElementById('noShowEscalationModal')).hide();
            let offcanvas = bootstrap.Offcanvas.getInstance(document.getElementById('applicantDrawer'));
            if(offcanvas) offcanvas.hide();
        },

        // --- SYS-ADMIN: ESCALATION RESOLUTION ---
        async resetEscalatedNoShow() {
            if(!this.selectedApplicant || !this.selectedApplicant.allottedDoj) return;
            this.selectedApplicant.status = 'Under Verification';
            this.selectedApplicant.isAdminEscalated = false;
            
            // FIRE TO TI-DB CLOUD
            await this.syncActionToCloud({
                ticket: this.selectedApplicant.ticket,
                status: 'Under Verification',
                remark: 'Silently reset Allotted DOJ and routed to HR-OPS.',
                allottedDoj: this.selectedApplicant.allottedDoj,
                isAdminEscalated: false,
                isGodMode: true
            });

            alert(`[AUDIT LOG] Stealth Override Complete.\nCandidate DOJ reset to ${this.formatDate(this.selectedApplicant.allottedDoj)}.\nPipeline routed back to Under Verification.`);
            let offcanvas = bootstrap.Offcanvas.getInstance(document.getElementById('applicantDrawer'));
            if(offcanvas) offcanvas.hide();
        },

        // --- NEW: CUSTOM PDF OVERRIDE HANDLER ---
        handleCustomOverrideUpload(event) {
            const file = event.target.files[0];
            if (!file) return;
            if (file.type !== 'application/pdf') {
                setTimeout(() => alert("STRICT COMPLIANCE ERROR: Only PDF formats are accepted for official overrides."), 10);
                event.target.value = '';
                return;
            }
            this.customOverrideFile = file.name;
            // Retain the File itself. Previously only the name was kept, so the
            // document never reached the server. It is uploaded at commit time
            // (not on selection) so an abandoned review leaves nothing behind.
            this.customOverrideFileObj = file;

            let idx = this.applications.findIndex(a => a.ticket === this.selectedApplicant.ticket);
            if (idx !== -1) {
                this.applications[idx].customOverrideFile = file.name;
                this.selectedApplicant = this.applications[idx];
            }
        },

        // Uploads the override and makes it the single live document for its
        // category. Returns true on success; the caller must NOT proceed with
        // the status change if this fails, or the record would advance while
        // still pointing at the old document.
        async uploadDocumentOverride(ticket, docType, remark) {
            if (!this.customOverrideFileObj) return true;
            const form = new FormData();
            form.append('ticket', ticket);
            form.append('doc_type', docType);
            form.append('file', this.customOverrideFileObj);
            form.append('remark', remark || 'Manual override by HR.');
            try {
                const response = await fetch('http://127.0.0.1:8000/api/hr/documents/override/', {
                    method: 'POST',
                    headers: this.authHeaders(),   // no Content-Type: the browser sets the multipart boundary
                    body: form
                });
                if (!response.ok) {
                    const detail = await response.text();
                    console.error('Document override rejected:', detail);
                    alert('Document override failed. The record has NOT been updated.\n\n' + detail);
                    return false;
                }
                this.customOverrideFileObj = null;
                return true;
            } catch (err) {
                console.error('Document override failed:', err);
                alert('Document override failed: the server could not be reached. The record has NOT been updated.');
                return false;
            }
        },

        // Uploads Annexure B to the SERVER.
        //
        // This used to set a filename in the browser and stop. The badge turned
        // green, the file never left the machine, and the clearance blocker
        // went on truthfully reporting Annexure B as missing -- which is
        // exactly what it was.
        async handleAnnexureBUpload(event) {
            const file = event.target.files[0];
            if (!file || !this.selectedApplicant) return;

            if (!file.name.toLowerCase().endsWith('.pdf')) {
                alert('Annexure B must be a PDF.');
                event.target.value = '';
                return;
            }
            if (file.size > 2 * 1024 * 1024) {
                alert('Annexure B must be under 2 MB.');
                event.target.value = '';
                return;
            }
            await this.uploadClearanceDocument('Annexure B', file, event.target);
        },

        // The DMRA exemption letter, when the candidate missed the session.
        async handleDmraExemptionUpload(event) {
            const file = event.target.files[0];
            if (!file || !this.selectedApplicant) return;
            if (!file.name.toLowerCase().endsWith('.pdf')) {
                alert('The exemption letter must be a PDF.');
                event.target.value = '';
                return;
            }
            await this.uploadClearanceDocument('DMRA Exemption Letter', file, event.target);
        },

        // Shared by both. Goes through the document override endpoint, so the
        // file lands in protected storage, supersedes any earlier version, and
        // is written to the audit ledger like every other document.
        async uploadClearanceDocument(docType, file, inputElement) {
            const form = new FormData();
            form.append('ticket', this.selectedApplicant.ticket);
            form.append('doc_type', docType);
            form.append('file', file);
            try {
                const response = await fetch('http://127.0.0.1:8000/api/hr/documents/override/', {
                    method: 'POST', headers: this.authHeaders(), body: form
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.error || `${docType} could not be uploaded.`);
                    if (inputElement) inputElement.value = '';
                    return;
                }
                await this.refreshAfterAction();
                // Re-ask the server what is still outstanding, so the button
                // unlocks the moment the last item lands.
                await this.saveClearance();
            } catch (err) {
                console.error('Clearance upload failed:', err);
                alert(`${docType} could not be uploaded: the server could not be reached.`);
            }
        },

        // Routes the drawer's document actions to the endpoint that owns them.
        //
        // This function used to decide the new status itself, upload an
        // override that took effect immediately, and then announce success in
        // an alert whether or not anything had happened. Each action now has a
        // server endpoint that owns the rule, and the answer comes from there.
        async executeDocumentDispatch(action) {
            if (!this.selectedApplicant) return;

            if (action === 'Sent for Re-Approval') {
                await this.submitOfferCorrection();
                return;
            }
            if (this.selectedApplicant.status === 'Offer Ready') {
                await this.confirmOfferHandover();
                return;
            }
            if (this.selectedApplicant.status === 'Pending Dispatch') {
                // The completion certificate and its dispatch email are the
                // next stage of the build.
                alert('Certificate dispatch is not implemented yet.');
                return;
            }
            alert(`No action is defined for '${action}' at status '${this.selectedApplicant.status}'.`);
        },

        // --- COLLEGE REFERRALS (PARALLEL WORKFLOW) ACTIONS ---
        //
        // Every one of these calls the server and then re-reads the list. None
        // of them mutates the local copy and hopes the server agrees: the old
        // implementation did exactly that, so a failed or refused action still
        // looked successful on screen until the page was refreshed.

        openNewReferralModal() {
            this.newReferralDraft = {
                cycleId: this.cyclesOpenForIntake.length ? this.cyclesOpenForIntake[0].id : '',
                department: '', collegeName: '', studentName: '',
                mobile: '', email: '', course: '', branch: '',
                course_other: '', branch_other: ''
            };
            new bootstrap.Modal(document.getElementById('newReferralModal')).show();
        },

        async submitNewReferral() {
            if (this.isSavingReferral || !this.newReferralIsValid) return;
            this.isSavingReferral = true;
            try {
                const d = this.newReferralDraft;
                const response = await fetch('http://127.0.0.1:8000/api/college-referrals/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        cycleId: d.cycleId,
                        studentName: d.studentName,
                        collegeName: d.collegeName,
                        email: d.email,
                        // Genuinely optional. A college's list is often
                        // incomplete, and these are collected in the full form.
                        mobile: d.mobile,
                        // Sent alongside the selection, exactly as the Phase-1
                        // form does. The server decides which one to store.
                        course: d.course,
                        course_other: d.course_other,
                        branch: d.branch,
                        branch_other: d.branch_other,
                        department: d.department
                    })
                });
                const data = await response.json().catch(() => ({}));

                if (!response.ok) {
                    alert(data.error || 'This intake could not be filed.');
                    return;
                }

                bootstrap.Modal.getInstance(document.getElementById('newReferralModal')).hide();
                await this.fetchCollegeReferrals();
                await this.fetchAuditLedger();
                this.referralTab = 'Intake Drafts';
                alert(`Intake filed as ${data.ticket}.`);
            } finally {
                this.isSavingReferral = false;
            }
        },

        // Correct what was taken down from the college's list. Recorded in the
        // audit ledger but not on the timeline -- a corrected spelling is
        // forensic detail, not an event in the candidate's story.
        // Puts a stored degree or branch back into its dropdown when the drawer
        // opens. A custom value matches no option, so without this the field
        // rendered blank and saving would have wiped it.
        seedIntakeEdits() {
            const acad = (this.selectedApplicant && this.selectedApplicant.academic) || {};
            const c = this.applyOptionValue(acad.course, this.courseOptions);
            const b = this.applyOptionValue(acad.branch, this.branchOptions);
            if (this.selectedApplicant && this.selectedApplicant.academic) {
                this.selectedApplicant.academic.course = c.selected;
                this.selectedApplicant.academic.branch = b.selected;
            }
            this.intakeCourseOther = c.other;
            this.intakeBranchOther = b.other;
        },

        // Matched without regard to case, because stored values are upper case
        // while the option labels are not.
        applyOptionValue(stored, options) {
            const value = (stored || '').trim();
            if (!value) return { selected: '', other: '' };
            const match = (options || []).find(o => o.toUpperCase() === value.toUpperCase());
            return match ? { selected: match, other: '' } : { selected: 'Other', other: value };
        },

        async saveIntakeEdits() {
            if (!this.selectedApplicant) return;
            const a = this.selectedApplicant;
            const acad = a.academic || {};
            if (acad.course === 'Other' && !this.intakeCourseOther.trim()) {
                alert('Enter the degree name, or choose one from the list.'); return;
            }
            if (acad.branch === 'Other' && !this.intakeBranchOther.trim()) {
                alert('Enter the specialization, or choose one from the list.'); return;
            }
            const result = await this.syncReferralAction({
                ticket: a.ticket,
                action: 'update',
                studentName: a.name,
                email: a.bio ? a.bio.email : '',
                mobile: a.bio ? a.bio.mobile : '',
                collegeName: acad.college || '',
                // Sent alongside the selection; the server decides which to store.
                course: acad.course || '',
                course_other: this.intakeCourseOther,
                branch: acad.branch || '',
                branch_other: this.intakeBranchOther,
                department: a.department || ''
            });
            if (result) {
                alert('Intake details corrected.');
                await this.refreshAfterAction();
            }
        },

        // Allot the reporting date and unit. Both are required: a date without
        // a posting tells the candidate when to come but not where.
        async executeReferralLogistics() {
            if (!this.selectedApplicant) return;
            if (!this.selectedApplicant.allottedDoj || !this.selectedApplicant.subDepartment) return;

            const result = await this.syncReferralAction({
                ticket: this.selectedApplicant.ticket,
                action: 'schedule',
                allottedDoj: this.selectedApplicant.allottedDoj,
                subDepartment: this.selectedApplicant.subDepartment
            });
            if (!result) return;

            alert(`Reporting date allotted.\nInform the candidate to report on `
                  + `${this.formatDate(this.selectedApplicant.allottedDoj)} `
                  + `at ${this.selectedApplicant.subDepartment}.`);
            this.closeApplicantDrawer();
        },

        // Open the full application form for this candidate. The ticket travels
        // in the URL and the form reads the record from the SERVER -- replacing
        // a localStorage handoff that carried a copy of the data between tabs
        // and could not survive a refresh.
        openReferralIntakeForm() {
            if (!this.selectedApplicant) return;
            const params = new URLSearchParams({ institutional: this.selectedApplicant.ticket });
            // devEmployeeCodes is a MAP keyed by role, not a single value. Reading
            // a non-existent `devEmployeeCode` yielded undefined, so no identity
            // was passed and the form opened as an ordinary referrer -- who has
            // no HR dashboard account, and so could not read the record at all.
            const devCode = this.isDevMode ? this.devEmployeeCodes[this.currentRole] : null;
            if (devCode) params.set('emp', devCode);
            window.open(`../Phase-1-User-Portal/index.html?${params.toString()}`, '_blank');
            this.closeApplicantDrawer();
        },

        // --- REJECTION ---------------------------------------------------
        openReferralRejectModal(fromNoShow = false) {
            if (!this.selectedApplicant) return;
            this.referralRejectData = {
                ticket: this.selectedApplicant.ticket,
                remark: '',
                fromNoShow: fromNoShow
            };
            if (fromNoShow) {
                const m = bootstrap.Modal.getInstance(document.getElementById('referralNoShowModal'));
                if (m) m.hide();
            }
            new bootstrap.Modal(document.getElementById('referralRejectModal')).show();
        },

        async executeReferralReject() {
            const reason = (this.referralRejectData.remark || '').trim();
            if (!reason) return;   // also enforced on the server

            const result = await this.syncReferralAction({
                ticket: this.referralRejectData.ticket,
                action: 'reject',
                remark: reason,
                fromNoShow: this.referralRejectData.fromNoShow
            });
            if (!result) return;

            bootstrap.Modal.getInstance(document.getElementById('referralRejectModal')).hide();
            this.closeApplicantDrawer();
            // The record leaves this section for the main pipeline's Rejected
            // tab, so that list needs re-reading too.
            await this.fetchLiveQueue();
            alert(`${this.referralRejectData.ticket} rejected and closed.`);
        },

        // --- NO-SHOW -----------------------------------------------------
        // One reschedule, then rejection only. The limit is enforced on the
        // server; this just stops the dialog offering what will be refused.
        triggerReferralNoShow() {
            if (!this.selectedApplicant) return;
            this.referralNoShowModalData = {
                ticket: this.selectedApplicant.ticket,
                currentDoj: this.selectedApplicant.allottedDoj,
                canReschedule: this.selectedApplicant.canReschedule !== false
            };
            this.tempReferralNoShowDoj = this.selectedApplicant.allottedDoj || null;
            new bootstrap.Modal(document.getElementById('referralNoShowModal')).show();

            this.$nextTick(() => {
                const el = document.getElementById('referralNoShowCalendar');
                if (!el) return;
                if (el._flatpickr) el._flatpickr.destroy();
                const approved = this.allowedDojDatesByCycle[this.selectedApplicant.cycle] || [];
                const fp = flatpickr(el, {
                    dateFormat: 'Y-m-d', altInput: true, altFormat: 'd-m-Y', minDate: 'today',
                    // Prefilled with the date the candidate missed, so HR is
                    // adjusting a known date rather than starting from nothing.
                    defaultDate: this.referralNoShowModalData.currentDoj || null,
                    // Approved dates are highlighted, others remain selectable:
                    // a candidate who missed their slot may need a date outside
                    // the published calendar.
                    onDayCreate: (dObj, dStr, fpObj, dayElem) => {
                        const y = dayElem.dateObj.getFullYear();
                        const m = String(dayElem.dateObj.getMonth() + 1).padStart(2, '0');
                        const d = String(dayElem.dateObj.getDate()).padStart(2, '0');
                        if (approved.includes(`${y}-${m}-${d}`)) dayElem.classList.add('ahr-approved-date');
                    },
                    onChange: (dates, str) => { this.tempReferralNoShowDoj = str; }
                });
                this.fpInstances.push(fp);
            });
        },

        async executeReferralNoShow() {
            if (!this.tempReferralNoShowDoj) return;
            const result = await this.syncReferralAction({
                ticket: this.referralNoShowModalData.ticket,
                action: 'reschedule',
                allottedDoj: this.tempReferralNoShowDoj
            });
            if (!result) return;

            bootstrap.Modal.getInstance(document.getElementById('referralNoShowModal')).hide();
            this.closeApplicantDrawer();
            alert(`New reporting date ${this.formatDate(this.tempReferralNoShowDoj)} allotted.\n`
                  + `This candidate's one reschedule has now been used. If they fail to `
                  + `report again, the application can only be rejected.`);
        },

        // --- ARRIVAL / MERGE ---------------------------------------------
        // The candidate reported. This is the moment the record joins the main
        // pipeline, and the date it happens becomes the actual date of joining
        // -- printed on the offer letter and the completion certificate, and
        // the basis of the projected end date.
        async markReferralArrived() {
            if (!this.selectedApplicant) return;

            const result = await this.syncReferralAction({
                ticket: this.selectedApplicant.ticket,
                action: 'arrive'
            });
            // Refused when something is still missing; syncReferralAction has
            // already listed exactly what.
            if (!result) return;

            this.closeApplicantDrawer();
            await this.fetchLiveQueue();
            alert(`Merged into the main pipeline.\n\n`
                  + `Date of joining recorded as ${this.formatDate(result.actualDoj)}.\n`
                  + `The application now awaits its offer letter in the `
                  + `HR-APP Pending Offers queue.`);
        },

        // --- ADMIN CONFIG FETCH ENGINE ---
        // Documents, sub-departments, quotas and joining dates all belong to ONE
        // cycle. DMRC runs concurrent cycles, so the cycle being viewed is sent
        // with every read -- the server no longer guesses, and what is on screen
        // is always the configuration of the cycle named in the selector.
        async fetchAdminConfigs() {
            try {
                const params = new URLSearchParams();
                if (this.adminSelectedCycle) params.set('cycleName', this.adminSelectedCycle);
                const response = await fetch(
                    `http://127.0.0.1:8000/api/admin/configs/?${params.toString()}`,
                    { headers: this.authHeaders() });
                if (response.ok) {
                    const data = await response.json();
                    this.dbSubDepartments = data.subDepts;
                    this.adminDocumentRules = data.docRules;
                    // What the server says these settings belong to. Used in the
                    // confirmation dialog, so the cycle named there is the one
                    // actually written to rather than the one assumed.
                    this.configCycleName = data.cycleName || this.adminSelectedCycle;
                } else {
                    console.error("GET Admin Configs failed with status:", response.status);
                }
            } catch (error) {
                console.error("Network error fetching Admin Configs:", error);
            }
        },

        // --- SYS-ADMIN ACTIONS & IAM ---
        async fetchIAMUsers() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/admin/iam/', { headers: this.authHeaders() });
                if (response.ok) {
                    this.iamUsers = await response.json();
                }
            } catch (error) {
                console.error("Network error fetching IAM Users:", error);
            }
        },

        openProvisionModal() {
            this.provisionData = { empId: '', role: 'HR-OPS' };
            this.provisionLookup = {};
            this.provisionLookupError = '';
            new bootstrap.Modal(document.getElementById('provisionUserModal')).show();
        },

        // Reads the employee out of the DMRC directory as the code is typed, so
        // the administrator sees WHO they are about to grant a role to before
        // granting it. An unknown code says so instead of failing at submit.
        async lookupEmployee() {
            const code = (this.provisionData.empId || '').trim();
            this.provisionLookup = {};
            this.provisionLookupError = '';
            if (code.length < 3) return;

            this.provisionLookupBusy = true;
            try {
                const response = await fetch(
                    `http://127.0.0.1:8000/api/admin/iam/?employee_code=${encodeURIComponent(code)}`,
                    { headers: this.authHeaders() }
                );
                const data = await response.json();
                if (!response.ok) {
                    this.provisionLookupError = data.error || 'That employee could not be found.';
                    return;
                }
                this.provisionLookup = data;
            } catch (err) {
                console.error('Directory lookup failed:', err);
                this.provisionLookupError = 'The directory could not be reached.';
            } finally {
                this.provisionLookupBusy = false;
            }
        },

        async executeProvisionUser() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/admin/iam/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    // The code and the role, and nothing else.
                    body: JSON.stringify({
                        empId: this.provisionData.empId,
                        role: this.provisionData.role
                    })
                });
                const data = await response.json();
                if (!response.ok) {
                    // The server's sentence, not a generic one: it explains
                    // whether the code is unknown, the role invalid, or the
                    // person already has an account.
                    alert(data.error || 'The account could not be created.');
                    return;
                }

                await this.fetchIAMUsers();
                await this.fetchAuditLedger();

                bootstrap.Modal.getInstance(document.getElementById('provisionUserModal')).hide();
                alert(data.message);
            } catch (error) {
                alert(`The account could not be created: ${error.message}`);
            }
        },

        async toggleIamStatus(user) {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/admin/iam/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ id: user.id })
                });
                
                if (!response.ok) throw new Error("Failed to toggle access.");
                
                // Refresh data from cloud
                await this.fetchIAMUsers();
                await this.fetchAuditLedger();
                
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        },

        // --- MASTER CYCLE ENGINE API INTEGRATIONS ---
        async fetchAdminCycles() {
            try {
                const params = new URLSearchParams();
                if (this.adminSelectedCycle) params.set('cycleName', this.adminSelectedCycle);
                const response = await fetch(
                    `http://127.0.0.1:8000/api/admin/cycles/?${params.toString()}`,
                    { headers: this.authHeaders() });
                if (response.ok) {
                    const data = await response.json();
                    this.adminCycles = data.cycles;
                    this.adminCapacities = data.capacities;
                    if (data.allowedDojDatesByCycle) {
                        this.allowedDojDatesByCycle = data.allowedDojDatesByCycle;
                    }
                    
                    if (this.activeCycles.length > 0 && !this.activeCycles.find(c => c.name === this.adminSelectedCycle)) {
                        this.adminSelectedCycle = this.activeCycles[0].name;
                    }
                } else {
                    console.error("GET Admin Cycles failed with status:", response.status);
                }
            } catch (error) {
                console.error("Network error fetching Master Cycles:", error);
            }
        },
        // ** CRITICAL FIX: Fully serializes and pushes the entire wizard array payload to TiDB **
        async executeInitializeCycle() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/admin/cycles/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        term: this.wizard.term, 
                        year: this.wizard.year,
                        start: this.wizard.start, 
                        end: this.wizard.end,
                        quotas: this.wizard.capacities,
                        subDepts: this.wizard.subDepts,
                        rules: this.wizard.docRules,
                        dojs: this.wizard.dojs
                    })
                });
                
                if (!response.ok) {
                    // Show the server's explanation. This used to throw a generic
                    // message, so an administrator saw "Failed to initialize cycle"
                    // with no indication of which field was at fault.
                    const detail = await response.text();
                    let reason = 'Failed to initialize cycle.';
                    try { reason = (JSON.parse(detail).error) || reason; } catch (e) {}
                    alert(reason);
                    return;
                }
                
                await this.fetchAdminCycles();
                await this.fetchAdminConfigs(); // Refresh configs to capture dynamic DB injection
                await this.fetchAuditLedger();
                this.adminSelectedCycle = `${this.wizard.term} ${this.wizard.year}`;
                
                bootstrap.Modal.getInstance(document.getElementById('cycleWizardModal')).hide();
                alert(`[AUDIT LOG] Cycle Initialized: ${this.wizard.term} ${this.wizard.year}`);
            } catch (error) { alert(`Error: ${error.message}`); }
        },

        async saveCycleDates() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/admin/cycles/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        action: 'edit_dates', cycleName: this.editDatesData.cycleName,
                        start: this.editDatesData.start, end: this.editDatesData.end
                    })
                });
                
                if (!response.ok) throw new Error("Failed to update dates.");
                
                await this.fetchAdminCycles();
                await this.fetchAuditLedger();
                bootstrap.Modal.getInstance(document.getElementById('editDatesModal')).hide();
            } catch (error) { alert(`Error: ${error.message}`); }
        },

        async confirmArchiveCycle(cycle) {
            // A cycle closes only when EVERY application in it has reached
            // Completed or Rejected.
            //
            // Two corrections here. 'Withdrawn' used to count as closeable, but
            // it is not one of the two terminal states -- a withdrawn record
            // must be rejected explicitly so a person decides its fate. And the
            // check read only `applications`, which no longer contains College
            // Referral records still being assembled; an abandoned intake would
            // have sailed through this check and been caught only by the server.
            const closed = ['Completed', 'Rejected'];
            const stragglers = [
                ...this.applications.filter(a => a.cycle === cycle.name && !closed.includes(a.status)),
                ...this.collegeReferrals.filter(a => a.cycle === cycle.name && !closed.includes(a.status))
            ];

            if (stragglers.length > 0) {
                const byStatus = {};
                stragglers.forEach(a => { byStatus[a.status] = (byStatus[a.status] || 0) + 1; });
                const lines = Object.entries(byStatus).map(([st, n]) => `  \u2022 ${st}: ${n}`).join('\n');
                alert(`${cycle.name} cannot be archived yet.\n\n`
                    + `${stragglers.length} application(s) have not reached Completed or Rejected:\n`
                    + `${lines}\n\n`
                    + `Complete or reject these before closing the cycle.`);
                return;
            }

            if(confirm(`WARNING: Are you sure you want to permanently archive ${cycle.name}? This will sweep applications to cold storage.`)) {
                try {
                    const response = await fetch('http://127.0.0.1:8000/api/admin/cycles/', {
                        method: 'PATCH',
                        headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                        body: JSON.stringify({ action: 'archive_cycle', cycleName: cycle.name })
                    });
                    
                    const data = await response.json().catch(() => ({}));

                    if (!response.ok) {
                        // A cycle can only close once every application in it is
                        // Completed or Rejected. The server lists what is still
                        // open, and those are shown here: "cannot archive" with
                        // no reason leaves an administrator with nowhere to go.
                        let message = data.error || 'Failed to archive cycle.';
                        if (Array.isArray(data.blockers) && data.blockers.length) {
                            message += '\n\nStill open:';
                            data.blockers.forEach(b => {
                                message += `\n  \u2022 ${b.status}: ${b.count}`
                                        + (b.tickets && b.tickets.length ? ` (${b.tickets.join(', ')}` : '')
                                        + (b.more ? ` and ${b.more} more)` : (b.tickets && b.tickets.length ? ')' : ''));
                            });
                            message += '\n\nComplete or reject these before archiving.';
                        }
                        alert(message);
                        return;
                    }

                    await this.fetchAdminCycles();
                    await this.fetchAuditLedger();
                    // Reload the vault so the cycle just closed is selectable
                    // straight away, rather than only after a page refresh.
                    await this.fetchArchives();
                    alert(`[AUDIT LOG] Master Sweep Complete. ${cycle.name} is permanently archived.`);
                } catch (error) { alert(`Error: ${error.message}`); }
            }
        },

        // ** CRITICAL FIX: Pushes targeted contextual capacity mapping to TiDB **
        saveQuotas() {
            const before = {};
            (this.adminCapacities || []).forEach(c => { before[c.dept] = c.quota; });
            const changes = (this.tempQuotas || [])
                .filter(q => String(before[q.dept]) !== String(q.quota))
                .map(q => `${q.dept}: ${before[q.dept] ?? '—'} -> ${q.quota} seats`);

            if (changes.length === 0) {
                bootstrap.Modal.getInstance(document.getElementById('editQuotasModal')).hide();
                return;
            }
            this.confirmCycleChange('Update capacity matrix', changes, () => this.commitQuotas());
        },

        async commitQuotas() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/admin/cycles/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ action: 'update_quotas', cycleName: this.adminSelectedCycle, quotas: this.tempQuotas })
                });
                
                if (!response.ok) throw new Error("Failed to update quotas.");
                
                await this.fetchAdminCycles();
                await this.fetchAuditLedger();
                bootstrap.Modal.getInstance(document.getElementById('editQuotasModal')).hide();
            } catch (error) { alert(`Error: ${error.message}`); }
        },

        // --- CYCLE WIZARD (Max 2 Logic Enforced) ---
        triggerWizardInit() {
            if (this.activeCycles.length >= 2) return;
            if (this.activeCycles.length === 1) {
                this.activeCycleNameForWarning = this.activeCycles[0].name;
                new bootstrap.Modal(document.getElementById('concurrentCycleWarningModal')).show();
            } else {
                this.openWizard();
            }
        },
        
        confirmConcurrentCycle() {
            bootstrap.Modal.getInstance(document.getElementById('concurrentCycleWarningModal')).hide();
            this.openWizard();
        },

        openWizard() {
            this.wizard = { step: 1, term: 'Summer', year: '2027', start: '', end: '', capacities: JSON.parse(JSON.stringify(this.adminCapacities)), subDepts: JSON.parse(JSON.stringify(this.dbSubDepartments)), docRules: JSON.parse(JSON.stringify(this.adminDocumentRules)), dojs: [] };
            this.newWizardRule = { name: '', isMandatory: true, format: '.pdf,.jpg,.jpeg', isActive: true };
            new bootstrap.Modal(document.getElementById('cycleWizardModal')).show();
            this.$nextTick(() => { this.initWizardCalendars(); });
        },
        initWizardCalendars() {
            this.wizardFpInstances.forEach(fp => fp.destroy());
            this.wizardFpInstances = [];
            this.wizardFpInstances.push(flatpickr(document.getElementById('wizStart'), { minDate: 'today', dateFormat: 'Y-m-d', onChange: (d, str) => this.wizard.start = str }));
            this.wizardFpInstances.push(flatpickr(document.getElementById('wizEnd'), { minDate: 'today', dateFormat: 'Y-m-d', onChange: (d, str) => this.wizard.end = str }));
        },
        initWizardDOJ() {
            flatpickr(document.getElementById('wizDoj'), { mode: 'multiple', dateFormat: 'Y-m-d', inline: true, minDate: 'today', onChange: (d, str) => this.wizard.dojs = str ? str.split(', ') : [] });
        },
        nextWizardStep() {
            // Step 1 collects the application window. Both dates are NOT NULL in
            // the database, so catching this here saves a failed round trip and
            // tells the administrator exactly what is missing.
            if (this.wizard.step === 1) {
                const gaps = [];
                if (!this.wizard.term)  gaps.push('session term');
                if (!this.wizard.year)  gaps.push('application year');
                if (!this.wizard.start) gaps.push('start date');
                if (!this.wizard.end)   gaps.push('end date');
                if (gaps.length) {
                    alert('Please provide the ' + gaps.join(', ') + ' before continuing.');
                    return;
                }
                if (this.wizard.start > this.wizard.end) {
                    alert('The start date cannot be after the end date.');
                    return;
                }
            }
            this.wizard.step++;
            if(this.wizard.step === 4) this.$nextTick(() => { this.initWizardDOJ(); });
        },
        addWizardRule() {
            if(this.newWizardRule.name.trim()) {
                this.wizard.docRules.push(JSON.parse(JSON.stringify(this.newWizardRule)));
                this.newWizardRule.name = '';
            }
        },

        // --- MID-CYCLE EDITS & ABSOLUTE BLOCK ---
        openEditDatesModal(cycle) {
            this.editDatesData.cycleName = cycle.name;
            this.editDatesData.start = cycle.start;
            this.editDatesData.end = cycle.end;
            new bootstrap.Modal(document.getElementById('editDatesModal')).show();
            this.$nextTick(() => {
                if(this.editDatesData.fpStart) this.editDatesData.fpStart.destroy();
                if(this.editDatesData.fpEnd) this.editDatesData.fpEnd.destroy();
                this.editDatesData.fpStart = flatpickr(document.getElementById('editDateStart'), { defaultDate: cycle.start, minDate: 'today', dateFormat: 'Y-m-d', onChange: (d, str) => this.editDatesData.start = str });
                this.editDatesData.fpEnd = flatpickr(document.getElementById('editDateEnd'), { defaultDate: cycle.end, minDate: 'today', dateFormat: 'Y-m-d', onChange: (d, str) => this.editDatesData.end = str });
            });
        },
        openEditQuotasModal() {
            this.tempQuotas = JSON.parse(JSON.stringify(this.adminCapacities));
            new bootstrap.Modal(document.getElementById('editQuotasModal')).show();
        },
        // --- CYCLE-SCOPED CONFIGURATION -----------------------------------
        //
        // Every configuration screen writes to ONE cycle, and DMRC runs more
        // than one at a time. So no change is applied until the administrator
        // has been shown WHICH cycle it lands on and WHAT is about to change.
        // Naming the cycle is the point: the mistake this prevents is editing
        // Winter while believing you are editing Summer.
        confirmCycleChange(title, changes, onConfirm) {
            this.pendingConfirm = {
                title: title,
                cycle: this.configCycleName || this.adminSelectedCycle || '—',
                changes: changes,
                run: onConfirm
            };
            new bootstrap.Modal(document.getElementById('cycleChangeConfirmModal')).show();
        },

        async executePendingConfirm() {
            const pending = this.pendingConfirm;
            const modal = bootstrap.Modal.getInstance(document.getElementById('cycleChangeConfirmModal'));
            if (modal) modal.hide();
            this.pendingConfirm = null;
            if (pending && typeof pending.run === 'function') await pending.run();
        },

        // Plain-language diff between the stored ruleset and the edited one, so
        // the dialog lists what actually changed rather than asking the
        // administrator to remember.
        describeRuleChanges() {
            const before = {};
            (this.adminDocumentRules || []).forEach(r => { before[r.name] = r; });
            const lines = [];

            (this.tempRules || []).forEach(rule => {
                const old = before[rule.name];
                if (!old) {
                    lines.push(`Add "${rule.name}" (${rule.isMandatory ? 'mandatory' : 'optional'})`);
                    return;
                }
                if (!!old.isActive !== !!rule.isActive) {
                    lines.push(`"${rule.name}" -> ${rule.isActive ? 'enabled' : 'disabled'}`);
                }
                if (!!old.isMandatory !== !!rule.isMandatory) {
                    lines.push(`"${rule.name}" -> ${rule.isMandatory ? 'mandatory' : 'optional'}`);
                }
                if (old.format !== rule.format) {
                    lines.push(`"${rule.name}" format -> ${rule.format}`);
                }
            });

            (this.pendingDocumentDeletions || []).forEach(name => {
                lines.push(`Remove "${name}" from this cycle`);
            });

            return lines;
        },

        openEditRuleSetModal() {
            this.tempRules = JSON.parse(JSON.stringify(this.adminDocumentRules));
            this.pendingDocumentDeletions = [];
            this.newRuleMidCycle = { name: '', isMandatory: true, format: '.pdf,.jpg,.jpeg', isActive: true };
            new bootstrap.Modal(document.getElementById('editRuleSetModal')).show();
        },
        addMidCycleRule() {
            if(this.newRuleMidCycle.name.trim()) {
                this.tempRules.push(JSON.parse(JSON.stringify(this.newRuleMidCycle)));
                this.newRuleMidCycle.name = '';
            }
        },
        // Deletions are collected and sent explicitly. The server refuses any
        // that are core or already used, disabling those instead, so a mistake
        // here can never orphan files or break archived records.
        pendingDocumentDeletions: [],

        deleteRule(idx) {
            const rule = this.tempRules[idx];
            if (!rule) return;
            if (!rule.canDelete) {
                alert(rule.isCore
                    ? `"${rule.name}" is a core document and cannot be deleted. Disable it instead.`
                    : `"${rule.name}" has already been used by an application, so deleting it would break those records. Disable it instead.`);
                return;
            }
            if (!confirm(`Delete "${rule.name}" permanently? This cannot be undone.`)) return;
            this.pendingDocumentDeletions.push(rule.name);
            this.tempRules.splice(idx, 1);
        },

        // True while a cycle is live, which freezes format and mandatory.
        get hasActiveCycle() {
            return (this.activeCycles || []).length > 0;
        },
        saveRuleSet() {
            // A name typed into the "add" row but never staged with the + button
            // is still a document the administrator meant to add. Discarding it
            // silently is how this appeared not to work at all: you type a name,
            // press Save, the dialog closes, and nothing has changed.
            this.addMidCycleRule();

            const changes = this.describeRuleChanges();
            if (changes.length === 0) {
                // Say so. Closing silently is indistinguishable from a save that
                // failed, which is exactly how it read.
                alert('No changes to save.\n\nType a document name and press + to add one, '
                    + 'or change a format, a mandatory tick or an enabled toggle.');
                return;
            }
            this.confirmCycleChange('Update document rules', changes, () => this.commitRuleSet());
        },

        async commitRuleSet() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/admin/configs/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        action: 'save_rules',
                        // The cycle these rules belong to. Without it the server
                        // would have to guess, which is how one cycle's settings
                        // used to overwrite another's.
                        cycleName: this.adminSelectedCycle,
                        rules: this.tempRules,
                        deleteDocuments: this.pendingDocumentDeletions
                    })
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.error || "Failed to save RuleSet.");

                await this.fetchAdminConfigs();
                await this.fetchAuditLedger();
                bootstrap.Modal.getInstance(document.getElementById('editRuleSetModal')).hide();
            } catch (error) { alert(`Error: ${error.message}`); }
        },

        openCalendarBuilderModal() {
            new bootstrap.Modal(document.getElementById('calendarBuilderModal')).show();
            this.$nextTick(() => {
                if(this.calendarBuilderData.fpInstance) this.calendarBuilderData.fpInstance.destroy();
                let activeDojs = this.allowedDojDatesByCycle[this.adminSelectedCycle] || [];
                this.calendarBuilderData.dojs = [...activeDojs];
                this.calendarBuilderData.fpInstance = flatpickr(document.getElementById('midCycleDoj'), {
                    mode: 'multiple', inline: true, minDate: 'today', defaultDate: activeDojs, dateFormat: 'Y-m-d',
                    onChange: (d, str) => { this.calendarBuilderData.dojs = str ? str.split(', ') : []; }
                });
            });
        },
        saveMasterCalendar() {
            const before = new Set(this.allowedDojDatesByCycle[this.adminSelectedCycle] || []);
            const after = new Set(this.calendarBuilderData.dojs || []);
            const added = [...after].filter(d => !before.has(d));
            const removed = [...before].filter(d => !after.has(d));
            const changes = [
                ...added.map(d => `Add joining date ${this.formatDate(d)}`),
                ...removed.map(d => `Remove joining date ${this.formatDate(d)}`)
            ];
            if (changes.length === 0) {
                bootstrap.Modal.getInstance(document.getElementById('calendarBuilderModal')).hide();
                return;
            }
            this.confirmCycleChange('Update joining dates', changes, () => this.commitMasterCalendar());
        },

        async commitMasterCalendar() {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/admin/cycles/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        action: 'save_master_calendar',
                        cycleName: this.adminSelectedCycle,
                        dojs: this.calendarBuilderData.dojs
                    })
                });

                if (!response.ok) throw new Error("Failed to save Master DOJ Calendar.");

                // Update local state and refresh audit logs
                this.allowedDojDatesByCycle[this.adminSelectedCycle] = [...this.calendarBuilderData.dojs];
                await this.fetchAuditLedger();

                bootstrap.Modal.getInstance(document.getElementById('calendarBuilderModal')).hide();
                this.calendarBuilderData.dojs = [];
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        },

        // --- SYS-ADMIN SIGNATURE & SUBDEPT ---
        // Kept as thin wrappers so the markup's @click handlers read the same
        // as before; the work is in decideSignature().
        async approveAdminSignature(sig) {
            if (!confirm(`Approve this signature for ${sig.name}?\n\nIt will be used on every offer letter they issue from now on. Letters already issued are not affected.`)) return;
            await this.decideSignature(sig, 'approve');
        },

        async rejectAdminSignature(sig) {
            // The reason is the ONLY thing telling the officer what to fix, so
            // it is required here and again on the server.
            const reason = prompt(`Why is this signature being returned to ${sig.name}?\n\nThey will see this reason.`);
            if (reason === null) return;
            if (!reason.trim()) {
                alert('A reason is required when returning a signature.');
                return;
            }
            await this.decideSignature(sig, 'reject', reason.trim().toUpperCase());
        },

        async addSubDept() {
            if(this.newSubDeptName.trim()) {
                // Upper case, matching every other field in the portal. The
                // server applies the same rule, so it holds regardless of client.
                let name = this.newSubDeptName.toUpperCase().trim();
                try {
                    const response = await fetch('http://127.0.0.1:8000/api/admin/configs/', {
                        method: 'POST',
                        headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                        body: JSON.stringify({ action: 'add_subdept', name: name, cycleName: this.adminSelectedCycle })
                    });
                    if (!response.ok) throw new Error("Failed to add Sub-Department.");
                    
                    this.newSubDeptName = '';
                    await this.fetchAdminConfigs();
                    await this.fetchAuditLedger();
                } catch (error) { alert(`Error: ${error.message}`); }
            }
        },
        toggleSubDept(dept) {
            this.confirmCycleChange(
                'Change sub-department availability',
                [`"${dept.name}" -> ${dept.isActive ? 'unavailable' : 'available'}`],
                () => this.commitSubDeptToggle(dept)
            );
        },

        async commitSubDeptToggle(dept) {
            try {
                const response = await fetch('http://127.0.0.1:8000/api/admin/configs/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        action: 'toggle_subdept',
                        name: dept.name,
                        // Scoped to this cycle. Toggling used to flip the unit's
                        // ORG-WIDE flag, so switching it off for one cycle
                        // removed it from every other running cycle as well.
                        cycleName: this.adminSelectedCycle
                    })
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) throw new Error(data.error || "Failed to toggle status.");

                await this.fetchAdminConfigs();
                await this.fetchAuditLedger();
            } catch (error) { alert(`Error: ${error.message}`); }
        },
        
        // --- ADMIN MODE OVERRIDE ------------------------------------------
        //
        // Replaces God Mode, which posted a whole-record overwrite through
        // HRApplicationActionAPIView with isGodMode: true. The differences
        // that matter:
        //
        //   - the SERVER decides which fields may be edited, from an
        //     allowlist, rather than this file deciding by what it happens
        //     to send
        //   - each corrected field gets its own audit row carrying the old
        //     value, the new value and the reason
        //   - a reset to Submitted is a real rollback: it clears the
        //     pipeline columns and withdraws the generated documents
        //   - issued documents a correction has outdated are flagged, and
        //     queued emails are rewritten to match
        //   - the capacity matrix is re-read from the server rather than
        //     adjusted here by arithmetic free to drift from it

        // Which drawer field maps to which server field. The values on the
        // right are the server's allowlist keys. Anything not listed here
        // cannot be sent, and anything the server does not recognise is
        // refused even if it were.
        ADMIN_FIELD_MAP: {
            'name':                     'students.full_name',
            'bio.father':               'students.fathers_name',
            'bio.gender':               'students.gender',
            'bio.dob':                  'students.date_of_birth',
            'bio.mobile':               'students.mobile_number',
            'bio.email':                'students.personal_email',
            'bio.aadhaar_number':       'students.aadhaar_number',
            'bio.address':              'students.permanent_address',
            'bio.emergencyName':        'students.emergency_contact_name',
            'bio.emergencyMobile':      'students.emergency_contact_mobile',
            'academic.university':      'academic_details.university_name',
            'academic.college':         'academic_details.college_name',
            'academic.course':          'academic_details.degree_program',
            'academic.branch':          'academic_details.branch_name',
            'academic.semester':        'academic_details.current_semester',
            'academic.grading':         'academic_details.grading_system',
            'academic.score':           'academic_details.current_score',
            'department':               'applications.department',
            'internship.duration':      'applications.duration_weeks',
            'ward':                     'applications.is_ward'
        },

        // Readable names for the confirmation dialog.
        ADMIN_FIELD_LABELS: {
            'name': 'Full name', 'bio.father': "Father's name",
            'bio.gender': 'Gender', 'bio.dob': 'Date of birth',
            'bio.mobile': 'Mobile', 'bio.email': 'Email',
            'bio.aadhaar_number': 'Aadhaar', 'bio.address': 'Address',
            'bio.emergencyName': 'Emergency contact',
            'bio.emergencyMobile': 'Emergency mobile',
            'academic.university': 'University', 'academic.college': 'College',
            'academic.course': 'Degree', 'academic.branch': 'Branch',
            'academic.semester': 'Semester',
            'academic.grading': 'Grading system', 'academic.score': 'Score',
            'department': 'Department', 'internship.duration': 'Duration',
            'ward': 'Ward application'
        },

        // Read a dotted path off selectedApplicant.
        adminReadPath(path) {
            return path.split('.').reduce(
                (obj, key) => (obj == null ? undefined : obj[key]),
                this.selectedApplicant);
        },

        captureAdminSnapshot() {
            const snap = {};
            Object.keys(this.ADMIN_FIELD_MAP).forEach(path => {
                snap[path] = this.adminReadPath(path);
            });
            return snap;
        },

        // The drawer shows dates as DD-MM-YYYY; the server wants YYYY-MM-DD.
        // Converting here rather than changing the display keeps the screen
        // reading the way DMRC staff expect.
        adminToIsoDate(value) {
            if (!value) return value;
            const text = String(value).trim();
            const parts = text.split(/[-\/]/);
            if (parts.length === 3 && parts[0].length <= 2) {
                const d = parts[0], m = parts[1], y = parts[2];
                return y + '-' + m.padStart(2, '0') + '-' + d.padStart(2, '0');
            }
            return text;   // already ISO, or something the server will reject
        },

        // Duration renders as either "4" or "4 Weeks" depending on the
        // select's options. Send the number either way.
        adminToWeeks(value) {
            const digits = String(value == null ? '' : value).match(/\d+/);
            return digits ? Number(digits[0]) : value;
        },

        // Build {serverKey: value} for the fields that actually changed, plus
        // a matching list of readable lines for the dialog.
        buildAdminChanges() {
            const changes = {};
            const lines = [];
            if (!this.adminSnapshot) return { changes: changes, lines: lines };

            Object.keys(this.ADMIN_FIELD_MAP).forEach(path => {
                const before = this.adminSnapshot[path];
                const after = this.adminReadPath(path);

                // Loose comparison on purpose: a select can turn 4 into "4"
                // without the administrator having touched anything.
                if (String(before == null ? '' : before) ===
                    String(after == null ? '' : after)) return;

                let value = after;
                if (path === 'bio.dob') value = this.adminToIsoDate(after);
                if (path === 'internship.duration') value = this.adminToWeeks(after);
                if (path === 'ward') value = !!after;

                changes[this.ADMIN_FIELD_MAP[path]] = value;

                const label = this.ADMIN_FIELD_LABELS[path] || path;
                const show = v => (v === '' || v == null) ? '(blank)' : String(v);
                lines.push(label + ': ' + show(before) + ' \u2192 ' + show(after));
            });

            return { changes: changes, lines: lines };
        },

        // Opens the confirmation dialog. NOTHING is written until the
        // administrator confirms there.
        async triggerAdminModeExecution() {
            if (!this.adminModeRemark.trim()) return;

            const built = this.buildAdminChanges();
            if (!built.lines.length && !this.adminModeStatus) {
                alert('Nothing has been changed. Edit a field or choose a status reset first.');
                return;
            }

            this.adminPendingChanges = built.lines;
            this.adminWarnings = null;

            // Only a reset can destroy anything, so only a reset needs the
            // warnings. A plain field correction skips the round trip.
            if (this.adminModeStatus) {
                try {
                    const response = await fetch(
                        API_BASE + '/api/admin/mode/?ticket=' +
                            encodeURIComponent(this.selectedApplicant.ticket),
                        { headers: this.authHeaders() });
                    const data = await response.json().catch(() => ({}));
                    if (response.ok) this.adminWarnings = data.warnings || null;
                } catch (error) {
                    // Not fatal. The dialog still lists the changes, it just
                    // cannot show the counts -- better than blocking a
                    // correction on a failed read.
                    console.warn('Could not load rollback warnings:', error);
                }
            }

            new bootstrap.Modal(document.getElementById('adminModeConfirmModal')).show();
        },

        async confirmAdminMode() {
            if (this.adminBusy) return;
            this.adminBusy = true;

            const built = this.buildAdminChanges();
            const payload = {
                ticket: this.selectedApplicant.ticket,
                reason: this.adminModeRemark.trim(),
                changes: built.changes
            };
            if (this.adminModeStatus) payload.status = this.adminModeStatus;

            try {
                const response = await fetch(API_BASE + '/api/admin/mode/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify(payload)
                });
                const data = await response.json().catch(() => ({}));

                if (!response.ok) {
                    // The server returns a per-field error map, so the
                    // administrator sees everything wrong with the patch at
                    // once rather than one problem per attempt.
                    if (data.errors) {
                        const detail = Object.keys(data.errors)
                            .map(k => '\u2022 ' + k + ': ' + data.errors[k]).join('\n');
                        throw new Error('Some changes were refused:\n\n' + detail);
                    }
                    throw new Error(data.detail || data.error || 'The override was refused.');
                }

                const modal = bootstrap.Modal.getInstance(
                    document.getElementById('adminModeConfirmModal'));
                if (modal) modal.hide();

                let summary = data.message || 'Correction applied.';
                if (data.documents_marked_stale && data.documents_marked_stale.length) {
                    summary += '\n\n' + data.documents_marked_stale.length +
                        ' issued document(s) are now marked out of date. Reissue them to clear the flag.';
                }
                if (data.documents_quarantined) {
                    summary += '\n\n' + data.documents_quarantined +
                        ' generated document(s) were withdrawn from circulation.';
                }
                if (data.notifications_rerendered) {
                    summary += '\n\n' + data.notifications_rerendered +
                        ' queued email(s) were updated to match.';
                }
                alert(summary);

                // Re-read rather than patch local state. Capacity counts,
                // document flags and the queue all moved server-side, and
                // guessing at them here is exactly what the old code got
                // wrong.
                this.adminEditMode = false;
                this.adminModeStatus = '';
                this.adminModeRemark = '';
                this.adminSnapshot = null;
                this.adminPendingChanges = [];
                this.adminWarnings = null;

                const offcanvas = bootstrap.Offcanvas.getInstance(
                    document.getElementById('applicantDrawer'));
                if (offcanvas) offcanvas.hide();

                await this.fetchLiveQueue();
                await this.fetchAuditLedger();
                if (typeof this.fetchAdminConfigs === 'function') {
                    await this.fetchAdminConfigs();
                }
            } catch (error) {
                alert('Error: ' + error.message);
            } finally {
                this.adminBusy = false;
            }
        },

        // --- NEW: FETCH FORENSIC DOCUMENTS LOGIC ---
        fetchForensicDocuments(ticketId, isArchived) {
            this.forensicData.ticket = ticketId;
            this.forensicData.isLoading = true;
            this.forensicData.candidateUploads = [];
            this.forensicData.officialDocuments = [];
            
            let app = this.applications.find(a => a.ticket === ticketId);
            // The archive is NOT searched here. It holds one page of rows, so
            // this matched only when the record happened to be on the page in
            // view -- and it is called from the Audit Ledger, which lists every
            // cycle ever run. `app` staying undefined is handled below.
            //
            // Every link in this modal now goes through the audited viewer --
            // documentHref() below for candidate uploads, and server-supplied
            // viewUrl/pdfUrl values for the official documents. Nothing here
            // builds a /media/ address any more, which is what used to 404 on
            // the intranet with DEBUG off.

            let modal = new bootstrap.Modal(document.getElementById('forensicDocumentModal'));
            modal.show();

            
            setTimeout(() => {
                let offerGenerated = app && this.OFFER_ISSUED_STATUSES.includes(app.status);
                let certGenerated = app && ['Pending Dispatch', 'Completed'].includes(app.status);
                
                // Construct Candidate Uploads using dynamic URLs from the TiDB backend response
                const uploads = [];
                // Built from the application's own requirement snapshot, so the
                // Forensic Inspector shows exactly the documents that record was
                // asked for -- including optional ones that were skipped, which
                // is materially different from a document being absent.
                if (app && app.docs) {
                    const rules = app.documentRules || [];
                    rules.forEach(rule => {
                        const entry = app.docs[rule.key];
                        if (entry) {
                            const fileName = typeof entry === 'string' ? entry.split('/').pop() : entry.name;
                            uploads.push({
                                name: rule.name,
                                fileName: fileName,
                                isMandatory: rule.isMandatory,
                                provided: true,
                                url: this.documentHref(entry)
                            });
                        } else {
                            // Nothing was uploaded. Common for a referral
                            // rejected before its documents were ever collected,
                            // and for optional documents the candidate skipped.
                            uploads.push({
                                name: rule.name,
                                fileName: rule.isMandatory ? 'MISSING' : 'NOT PROVIDED (OPTIONAL)',
                                isMandatory: rule.isMandatory,
                                provided: false,
                                url: null
                            });
                        }
                    });
                }
                this.forensicData.candidateUploads = uploads;
                
                // Construct Official Documents
                // url is null when nothing has been generated. It used to be
                // '#', which resolves to the dashboard's own address -- so the
                // link opened a duplicate dashboard rather than doing nothing.
                // The REAL offer letter, from the application record: the
                // latest version HR-APP approved, whether that is the generated
                // one or a correction that replaced it.
                //
                // This used to build a /media/generated_docs/Offer_<ticket>.pdf
                // address by hand. No such file has ever existed -- generated
                // documents are stored outside the served directories and
                // reached only through the audited viewer -- so the link 404'd,
                // and on the intranet it would have 404'd even if the file were
                // there, because Django serves nothing from /media/ with DEBUG
                // off.
                const offer = (app && app.offerLetter) || {};
                const cert = (app && app.certificate) || {};
                const annexure = app && app.annexureB;
                const exemption = app && app.dmraExemption;
                this.forensicData.officialDocuments = [
                    { name: 'Offer Letter',
                      fileName: offer.issued ? (offer.fileName || `Offer_Letter_${ticketId}.pdf`) : 'N/A',
                      isGenerated: !!offer.issued,
                      detail: offer.issued
                          ? `Version ${offer.version} · issued ${offer.issuedOn} · signed by ${offer.signedBy || '—'}`
                          : 'Not yet issued.',
                      // Downloadable, unlike a candidate's identity documents:
                      // this is DMRC's own letter and HR-OPS has to print it.
                      // The download is still role-checked and still logged.
                      url: offer.issued ? offer.pdfUrl : null },
                    // The certificate, shown only once the application is
                    // COMPLETED -- before dispatch it can still be corrected and
                    // re-approved, so an earlier version is not the document the
                    // candidate received. Same rule as the vault.
                    { name: 'Completion Certificate',
                      fileName: (app && app.status === 'Completed' && cert.issued)
                          ? (cert.fileName || `Completion_Certificate_${ticketId}.pdf`) : 'N/A',
                      isGenerated: !!(app && app.status === 'Completed' && cert.issued),
                      detail: (app && app.status === 'Completed' && cert.issued)
                          ? `Version ${cert.version} · issued ${cert.issuedOn} · signed by ${cert.signedBy || '—'}`
                          : (cert.issued ? 'Issued but not yet dispatched.' : 'Not yet issued.'),
                      url: (app && app.status === 'Completed' && cert.issued) ? cert.pdfUrl : null },

                    // CLEARANCE PAPERWORK. Uploaded by HR rather than generated,
                    // but official all the same -- and an auditor asking what was
                    // collected at exit should find it here rather than having to
                    // open the application drawer.
                    { name: 'Annexure B',
                      fileName: annexure ? (annexure.fileName || 'Annexure B') : 'N/A',
                      isGenerated: !!annexure,
                      detail: annexure ? 'Collected at clearance.' : 'Not uploaded.',
                      url: annexure ? annexure.viewUrl : null },

                    // Only ever present when the candidate MISSED the DMRA
                    // session, so its absence is meaningful rather than a gap.
                    { name: 'DMRA Exemption Letter',
                      fileName: exemption ? (exemption.fileName || 'DMRA Exemption Letter') : 'N/A',
                      isGenerated: !!exemption,
                      detail: exemption
                          ? 'Candidate missed the DMRA session.'
                          : 'Not applicable — the candidate attended.',
                      url: exemption ? exemption.viewUrl : null }
                ];
                
                this.forensicData.isLoading = false;
            }, 600); 
        },

        // Absolute, identity-carrying link to ONE stored document, or null if
        // there is nothing to open.
        //
        // Three things have to be right, and the Forensic Inspector got none of
        // them:
        //
        //  * THE KEY. The queue sends `viewUrl`; the inspector read
        //    `previewUrl`, which is the REFERRER portal's field name. The result
        //    was undefined -- and Alpine renders an undefined :href as href="",
        //    which resolves to the current page. So every View button opened a
        //    second copy of the dashboard instead of the document.
        //
        //  * THE ORIGIN. viewUrl is root-relative ("/api/documents/view/?t=..").
        //    The dashboard is not served by Django, so it must be prefixed with
        //    the API host or it resolves against the static server and 404s.
        //
        //  * THE IDENTITY. Opening a document is a plain browser navigation and
        //    carries no custom header, so in development identity would fall
        //    back to the default employee. The viewer checks the caller's role
        //    and writes every access to the audit ledger, so it must be told who
        //    is actually looking.
        documentHref(entry) {
            if (!entry) return null;
            // A bare string is a legacy path with no viewer token. It cannot be
            // opened through the audited viewer, and linking straight into
            // /media/ would both bypass the access log and 404 for anything in
            // protected storage. Treated as not viewable.
            if (typeof entry === 'string') return null;

            const path = entry.viewUrl || entry.previewUrl;
            if (!path) return null;

            const emp = this.identity ? this.identity.employeeCode : '';
            const joiner = path.includes('?') ? '&' : '?';
            return `http://127.0.0.1:8000${path}${joiner}emp=${encodeURIComponent(emp)}`;
        },

        // Downloads a generated document from the Forensic Inspector.
        //
        // The inspector opens on applications the drawer is not showing, so it
        // cannot reuse downloadOfferLetter() -- that reads selectedApplicant.
        // The URL already carries the ticket; this only has to add the identity
        // and turn the response into a file.
        // Opens a generated document from the Forensic Inspector in a new tab.
        //
        // The inspector shows applications the drawer is not holding, so it
        // cannot reuse downloadOfferLetter(), which reads selectedApplicant.
        openForensicDocument(doc) {
            if (!doc || !doc.url) return;
            const emp = this.identity ? this.identity.employeeCode : '';
            const joiner = doc.url.includes('?') ? '&' : '?';
            window.open(`http://127.0.0.1:8000${doc.url}${joiner}emp=${encodeURIComponent(emp)}`, '_blank');
            setTimeout(() => this.fetchAuditLedger(), 800);
        },

        // Absolute, identity-carrying link to a stored signature image.
        //
        // signatureHref is separate from documentHref for the same reason
        // signatures are stored separately: they are the one file whose theft
        // lets somebody forge a DMRC document, so they never travel through the
        // document viewer.
        //
        // Both parts matter. The server returns a root-relative path
        // ("/api/signatures/image/?t=.."), and the dashboard is NOT served by
        // Django -- so without the API host the browser asks the static server
        // and gets nothing, which is why the panel showed a broken image. And an
        // <img> tag is a plain browser fetch carrying no custom header, so in
        // development it must say who is looking or the identity falls back to
        // the default employee and the role check means nothing.
        signatureHref(path) {
            if (!path) return null;
            const emp = this.identity ? this.identity.employeeCode : '';
            const joiner = path.includes('?') ? '&' : '?';
            return `http://127.0.0.1:8000${path}${joiner}emp=${encodeURIComponent(emp)}`;
        },

        // Every department the portal knows about, gathered from what is
        // actually in use plus the cycle's own list.
        //
        // Preferred over a hardcoded set for two reasons: the literals drifted
        // out of case with the stored values and silently mis-displayed every
        // drawer, and a department DMRC adds later would never have appeared.
        get departmentOptions() {
            const seen = new Set();
            (this.referralDepartments || []).forEach(d => d && seen.add(String(d).toUpperCase()));
            (this.applications || []).forEach(a => a.department && seen.add(String(a.department).toUpperCase()));
            (this.collegeReferrals || []).forEach(a => a.department && seen.add(String(a.department).toUpperCase()));
            return [...seen].sort();
        },

        // Does one record match the omni-search? Used by the Verification
        // Queue AND the College Referrals pipeline, so a term that finds a
        // candidate in one finds them in the other.
        //
        // Department, college and university were missing: those are exactly
        // the terms somebody reaches for when they are looking at a list rather
        // than for one known person -- "show me everyone from DTU".
        matchesSearch(app, query) {
            if (!query) return true;
            const bio = app.bio || {};
            const academic = app.academic || {};
            const fields = [
                app.ticket, app.name, app.referrerName, app.department,
                app.status, app.subDepartment, app.approvalRefId,
                academic.college, academic.university, academic.course, academic.branch,
                bio.email, bio.aadhaar_number,
                app.referrer && app.referrer.id,
            ];
            if (fields.some(v => v && String(v).toUpperCase().includes(query))) return true;
            // Numbers are matched without upper-casing, which would be a no-op
            // and only obscures the intent.
            return !!(bio.mobile && String(bio.mobile).includes(query));
        },

        // --- CALENDAR & UTILS ---
        // Projects an end date from a joining date and a duration.
        //
        // This used to ASSUME FOUR WEEKS whenever it could not find a number in
        // the duration text, which happens whenever the duration has not been
        // chosen yet. An application with no duration therefore displayed and
        // sorted as a confident four-week internship. It now returns a dash, and
        // a dash on a new application is correct rather than broken: the
        // database allows a not-yet-chosen duration, and the offer letter
        // refuses to issue without one.
        //
        // The number of weeks is read from internship.weeks, which the server
        // sends as a number. The old text is still accepted so that anything
        // calling this with an older payload keeps working.
        calculateCompletionDate(dojStr, internshipObj) {
            if (!dojStr) return '—';
            let parts = String(dojStr).split('-');
            if (parts.length !== 3) return dojStr;

            let weeks = null;
            if (internshipObj) {
                if (typeof internshipObj.weeks === 'number') weeks = internshipObj.weeks;
                else if (internshipObj.duration) {
                    const match = String(internshipObj.duration).match(/\d+/);
                    if (match) weeks = parseInt(match[0]);
                }
            }
            if (!weeks || weeks <= 0) return '—';

            let date = new Date(parts[0], parts[1] - 1, parts[2]);
            date.setDate(date.getDate() + (weeks * 7));
            let y = date.getFullYear();
            let m = String(date.getMonth() + 1).padStart(2, '0');
            let d = String(date.getDate()).padStart(2, '0');
            return `${y}-${m}-${d}`;
        },

        // THE end date for one record, in ISO form, or '' when there is none.
        //
        //   1. the date STORED when the offer letter was issued, if there is
        //      one. That is the date printed on the letter and the certificate,
        //      so the queue now agrees with the documents -- including after an
        //      administrator corrects it, which the old estimate ignored.
        //   2. otherwise a projection from the joining date that matters for
        //      this record's status, plus its duration.
        //   3. otherwise nothing.
        //
        // The column on screen and the sort both read this, so a row can no
        // longer show a dash while being ordered by a value nobody can see.
        completionDateRaw(app) {
            if (!app) return '';
            if (app.completionDate) return app.completionDate;

            // Nothing is projected before a date has been committed. Until then
            // the only date available is one the candidate ASKED for, and
            // printing an end date derived from a request reads as a promise.
            if (['Submitted', 'Under Verification', 'Rejected', 'Intake Draft'].includes(app.status)) return '';

            const doj = this.getDisplayDojValue(app);
            if (!doj) return '';
            const projected = this.calculateCompletionDate(doj, app.internship);
            return projected === '—' ? '' : projected;
        },

        // The same date formatted for display: DD-MM-YYYY, a dash when unknown,
        // and prefixed 'Est.' while it is still a projection, so nobody plans a
        // dispatch around a date that can still move.
        completionDateDisplay(app) {
            const raw = this.completionDateRaw(app);
            if (!raw) return '—';
            if (app && app.completionDate) return this.formatDate(raw);
            return `Est. ${this.formatDate(raw)}`;
        },

        getLatestResubDate(app) {
            let d1 = app.documentResubmissionDetails?.date;
            let d2 = app.dojResubmissionDetails?.date;
            if (d1 && d2) return (new Date(d1) > new Date(d2)) ? d1 : d2;
            return d1 || d2 || null;
        },

        get escalatedQueue() {
            return this.applications.filter(app => app.status === 'Rejected' && app.isAdminEscalated);
        },
        
        // The three College Referrals tabs. Sourced from collegeReferrals, NOT
        // from applications -- see the note on that state field.
        get intakeDrafts() { return this.collegeReferrals.filter(a => a.status === 'Intake Draft'); },
        get reportingQueue() { return this.collegeReferrals.filter(a => a.status === 'Pending Arrival'); },
        get readyForMergeQueue() { return this.collegeReferrals.filter(a => a.status === 'Ready for Merge'); },

        get referralsForActiveTab() {
            if (this.referralTab === 'Intake Drafts') return this.intakeDrafts;
            if (this.referralTab === 'Pending Arrival') return this.reportingQueue;
            return this.readyForMergeQueue;
        },

        // The active tab with the search applied. This is what the table renders
        // AND what the export sends, so the file can only ever contain what is
        // on screen.
        get filteredCollegeReferrals() {
            const query = (this.referralSearch || '').trim().toUpperCase();
            return this.referralsForActiveTab.filter(a => this.matchesSearch(a, query));
        },

        // Only cycles still inside their application window may take a new
        // intake. Closed cycles stay visible elsewhere so existing records
        // remain workable, but nothing new can be filed against them.
        get cyclesOpenForIntake() {
            return this.referralCycles.filter(c => c.acceptsNewIntake);
        },

        get newReferralIsValid() {
            const d = this.newReferralDraft;
            const base = !!(d.cycleId && (d.studentName||'').trim() && (d.collegeName||'').trim() && (d.email||'').trim());
            // Degree and branch are optional here -- a college's list is often
            // incomplete, and the merge check refuses to let a record into the
            // pipeline without them. But choosing "Other" and typing nothing
            // would store the literal word OTHER, which is the very thing this
            // change exists to stop.
            const courseOk = d.course !== 'Other' || !!(d.course_other||'').trim();
            const branchOk = d.branch !== 'Other' || !!(d.branch_other||'').trim();
            return base && courseOk && branchOk;
        },

        get processedQueue() {
            let result = this.applications;

            if (this.activeTab !== 'All') {
                if (this.activeTab === 'Pending') result = result.filter(app => ['Submitted', 'Under Verification'].includes(app.status));
                else if (this.activeTab === 'Resubmissions') result = result.filter(app => app.isResubmitted || app.hasUsedDocumentLifeline || app.hasUsedDojLifeline);
                else if (this.activeTab === 'Approved') result = result.filter(app => app.status === 'Approved');
                else if (this.activeTab === 'Active') result = result.filter(app => app.status === 'Joined');
                else if (this.activeTab === 'Ready for Handover') result = result.filter(app => app.status === 'Offer Ready');
                else if (this.activeTab === 'Rejected') result = result.filter(app => app.status === 'Rejected' && !app.isAdminEscalated);   // includes bounces parked with the referrer (awaitingReferrerAction)
                else if (this.activeTab === 'Pending Offer Letter') result = result.filter(app => ['Pending Offer Letter', 'Pending Offer Re-Approval'].includes(app.status));
                // Pending Dispatch belongs HERE too. A certificate that has been
                // signed but not yet sent is still an open piece of work, and
                // the Verification Queue is the operational view of everything
                // outstanding -- it should not lose sight of an intern between
                // HR-APP signing the certificate and dispatching it.
                //
                // The application leaves this tab when it becomes Completed,
                // which happens only when HR-APP actually sends it.
                //
                // HR-APP's own dashboard is different: there, Pending
                // Certificates and Ready for Dispatch are separate queues,
                // because those are two different things for that officer to do.
                else if (this.activeTab === 'Pending Certificate') result = result.filter(app => ['Pending Certificate', 'Pending Dispatch'].includes(app.status));
                else result = result.filter(app => app.status === this.activeTab);
            } else {
                // Staging records are no longer present in `applications` at
                // all -- the server excludes them -- so only escalations need
                // filtering here.
                result = result.filter(app => !app.isAdminEscalated); 
            }

            if (this.filters.cycle) result = result.filter(app => app.cycle === this.filters.cycle);
            if (this.filters.department) result = result.filter(app => app.department === this.filters.department);
            if (this.filters.subDepartment) result = result.filter(app => app.subDepartment === this.filters.subDepartment);

            // Target DOJ is matched against THE DATE THAT MATTERS FOR THAT
            // RECORD, not against one fixed column. This compared the requested
            // date for everybody, so a candidate moved to a different date was
            // still filed under the date they originally asked for, and anyone
            // who had already joined could not be found by the date they
            // actually arrived on.
            if (this.filters.specificDoj) {
                result = result.filter(app => this.getDisplayDojValue(app) === this.filters.specificDoj);
            }

            if (this.filters.evaluationResult) result = result.filter(app => app.evaluationResult === this.filters.evaluationResult);
            if (this.filters.isWaitlisted) result = result.filter(app => app.waitlisted === true);
            if (this.filters.isWard) result = result.filter(app => app.ward === true);

            // WHY THESE READ rejectionCategory AND NOT hasUsedDocumentLifeline
            // / hasUsedDojLifeline: the server sends both of those as a fixed
            // false for every application, so the two filters that used to read
            // them returned an empty table whatever was in the database.
            //
            // Those two fields are left exactly as they are. They also control
            // the reject buttons and two row badges, and switching them on would
            // change the reject flow -- a separate decision, not part of a
            // filter change.
            //
            // rejectionCategory records WHY an application was last returned:
            // 'Invalid Document' for a correction, 'No Show' for a new joining
            // date. Its limit, stated plainly: it holds the LATEST reason only,
            // so a candidate returned for documents and later for a no-show
            // counts as a no-show here. Recording every bounce separately would
            // need a new table.
            //
            // The two boxes are an EITHER/OR: ticking both shows everything that
            // has been returned to the referrer for any reason. Read as an AND
            // they would always come back empty, since a record carries one
            // reason at a time.
            if (this.filters.correctionBounce || this.filters.dojBounce) {
                result = result.filter(app => {
                    if (this.filters.correctionBounce && app.rejectionCategory === 'Invalid Document') return true;
                    if (this.filters.dojBounce && app.rejectionCategory === 'No Show') return true;
                    return false;
                });
            }

            // Has spent the one and only reschedule. dojLifelineUsed counts the
            // rescheduled dates actually issued, and the server deliberately
            // does NOT count a date an administrator changed -- an escalation
            // asks an administrator to fix a date, it is not the candidate's
            // second chance. A college candidate rescheduled by HR does count:
            // the operational fact is the same, they cannot be given another.
            if (this.filters.dojRescheduleUsed) result = result.filter(app => app.dojLifelineUsed === true);

            if (this.masterSearch.trim() !== '') {
                const query = this.masterSearch.toUpperCase();
                result = result.filter(app => this.matchesSearch(app, query));
            }

            // --- SORTING -------------------------------------------------
            //
            // Every sort reads one value per record and compares it the same
            // way, with ONE rule for missing values: A RECORD WITH NOTHING TO
            // SORT BY SINKS TO THE BOTTOM, in both directions.
            //
            // The old code pushed unknown completion dates to the end by
            // pretending they fell in the year 275760. That reads correctly
            // ascending and inverts descending, so 'latest first' would have
            // opened with a screenful of dashes. This is the same rule the
            // Archives screen already applies, for the same reason.
            //
            // Dates are compared as ISO text (YYYY-MM-DD), which sorts
            // chronologically without building a Date object for every
            // comparison, and without an invalid date silently becoming NaN.
            const sortValue = (app) => {
                switch (this.sortBy) {
                    case 'submission_asc':
                    case 'submission_desc':
                        return app.date || '';
                    case 'resubmission_asc':
                    case 'resubmission_desc':
                        // The most recent correction or new-date response. A
                        // record that has never been returned has none, and
                        // sinks rather than being stood in for by its
                        // submission date.
                        return this.getLatestResubDate(app) || '';
                    case 'doj_asc':
                    case 'doj_desc':
                        // The same status-aware date the column and the Target
                        // DOJ filter use.
                        return this.getDisplayDojValue(app) || '';
                    case 'completion_asc':
                    case 'completion_desc':
                        return this.completionDateRaw(app) || '';
                    case 'ticket_asc':
                    case 'ticket_desc':
                        return app.ticket || '';
                    default:
                        return '';
                }
            };

            const descending = this.sortBy.endsWith('_desc');
            const direction = descending ? -1 : 1;

            // Ticket numbers restart at 001 in every cycle, so DMRC-2026S-047
            // and DMRC-2026W-047 are two unrelated people and ordering a mixed
            // list by ticket produces a sequence that means nothing. The drawer
            // greys the option out until a cycle is chosen; this is the same
            // rule enforced where the sorting actually happens, so clearing the
            // cycle while ticket order is active cannot leave a misleading list
            // on screen.
            const ticketOrder = this.sortBy === 'ticket_asc' || this.sortBy === 'ticket_desc';
            if (ticketOrder && !this.filters.cycle) {
                return [...result].sort((a, b) => {
                    const av = a.date || '', bv = b.date || '';
                    if (!av && !bv) return 0;
                    if (!av) return 1;
                    if (!bv) return -1;
                    return av < bv ? -1 : av > bv ? 1 : 0;
                });
            }

            return [...result].sort((a, b) => {
                const av = sortValue(a);
                const bv = sortValue(b);
                if (!av && !bv) return 0;
                if (!av) return 1;      // blanks sink, whatever the direction
                if (!bv) return -1;
                if (av === bv) return 0;
                return (av < bv ? -1 : 1) * direction;
            });
        },

        // --- PAGING: THE VERIFICATION QUEUE ------------------------------
        //
        // processedQueue stays the FULL filtered and sorted list. Everything
        // that must act on the whole result -- the record count, the exports --
        // keeps reading it. Only the table reads pagedQueue.
        get queuePageCount() {
            return Math.max(1, Math.ceil(this.processedQueue.length / this.PAGE_SIZE));
        },

        // The page actually being shown. Clamped rather than corrected in
        // place: a getter that writes to state re-triggers itself, and a
        // filter that shortens the list would otherwise leave the table
        // empty with the pager still claiming to be on page 7 of 2.
        get queueCurrentPage() {
            return Math.min(Math.max(1, this.queuePage), this.queuePageCount);
        },

        get pagedQueue() {
            const start = (this.queueCurrentPage - 1) * this.PAGE_SIZE;
            return this.processedQueue.slice(start, start + this.PAGE_SIZE);
        },

        // 'Showing 26-50 of 312'. Reads 0 of 0 on an empty result rather than
        // '1-0 of 0'.
        get queueRangeLabel() {
            const total = this.processedQueue.length;
            if (total === 0) return '0 of 0';
            const start = (this.queueCurrentPage - 1) * this.PAGE_SIZE + 1;
            return `${start}\u2013${Math.min(start + this.PAGE_SIZE - 1, total)} of ${total}`;
        },

        // The page numbers to offer. Every page while there are few, and a
        // window around the current one once there are many, so the control
        // does not grow into a second table of its own.
        get queuePageNumbers() {
            return this.pageNumbersFor(this.queueCurrentPage, this.queuePageCount);
        },

        goToQueuePage(page) {
            const target = Math.min(Math.max(1, page), this.queuePageCount);
            if (target === this.queueCurrentPage) return;
            this.queuePage = target;
            // A selection may only ever contain rows that are on screen. The
            // bulk ribbon acts on everything selected, and approving people the
            // officer can no longer see is the one outcome worth designing out.
            this.selectedRows = [];
        },

        // --- PAGING: COLLEGE REFERRALS -----------------------------------
        get referralPageCount() {
            return Math.max(1, Math.ceil(this.filteredCollegeReferrals.length / this.PAGE_SIZE));
        },

        get referralCurrentPage() {
            return Math.min(Math.max(1, this.referralPage), this.referralPageCount);
        },

        get pagedCollegeReferrals() {
            const start = (this.referralCurrentPage - 1) * this.PAGE_SIZE;
            return this.filteredCollegeReferrals.slice(start, start + this.PAGE_SIZE);
        },

        get referralRangeLabel() {
            const total = this.filteredCollegeReferrals.length;
            if (total === 0) return '0 of 0';
            const start = (this.referralCurrentPage - 1) * this.PAGE_SIZE + 1;
            return `${start}\u2013${Math.min(start + this.PAGE_SIZE - 1, total)} of ${total}`;
        },

        get referralPageNumbers() {
            return this.pageNumbersFor(this.referralCurrentPage, this.referralPageCount);
        },

        goToReferralPage(page) {
            const target = Math.min(Math.max(1, page), this.referralPageCount);
            if (target === this.referralCurrentPage) return;
            this.referralPage = target;
            this.selectedRows = [];
        },

        // Shared by both pagers. Up to seven numbers, centred on the current
        // page and pinned to the ends of the range.
        pageNumbersFor(current, count) {
            const WINDOW = 7;
            if (count <= WINDOW) return Array.from({ length: count }, (_, i) => i + 1);
            let first = Math.max(1, current - Math.floor(WINDOW / 2));
            let last = first + WINDOW - 1;
            if (last > count) { last = count; first = count - WINDOW + 1; }
            return Array.from({ length: WINDOW }, (_, i) => first + i);
        },

        // Watched so that changing a tab, a filter, the sort or the search
        // returns to page one. Without it, narrowing a 300-record list while on
        // page 8 leaves an empty table on screen, which reads as a broken queue
        // rather than as a filter that matched fewer records.
        //
        // Written as a single value rather than one watcher per control: a
        // watcher on the filters OBJECT does not fire when a field inside it
        // changes, and a filter added later would silently stop resetting.
        get queueViewFingerprint() {
            const f = this.filters;
            return [this.activeTab, this.sortBy, this.masterSearch,
                    f.cycle, f.department, f.subDepartment, f.specificDoj,
                    f.evaluationResult, f.correctionBounce, f.dojBounce,
                    f.isWaitlisted, f.isWard, f.dojRescheduleUsed].join('|');
        },

        get referralViewFingerprint() {
            return [this.referralTab, this.referralSearch].join('|');
        },

        get pendingOffers() { return this.applications.filter(a => a.status === 'Pending Offer Letter' || a.status === 'Pending Offer Re-Approval'); },        get pendingCertificates() { return this.applications.filter(a => a.status === 'Pending Certificate'); },
        get readyForDispatch() { return this.applications.filter(a => a.status === 'Pending Dispatch'); },

        formatDate(isoString) {
            if (!isoString) return '—';
            const parts = isoString.split('-');
            if(parts.length !== 3) return isoString; 
            return `${parts[2]}-${parts[1]}-${parts[0]}`;
        },

        clearFilters() {
            this.filters = {
                cycle: '', department: '', subDepartment: '', specificDoj: '', evaluationResult: '',
                correctionBounce: false, dojBounce: false,
                isWaitlisted: false, isWard: false, dojRescheduleUsed: false
            };
            this.masterSearch = '';
            // The calendar holds its own copy of the chosen date, so clearing
            // the filter has to clear the widget too or the drawer would keep
            // showing a date that is no longer being applied.
            const el = document.getElementById('queueDojFilter');
            if (el && el._flatpickr) el._flatpickr.clear();
            // Ticket order needs a cycle. Clearing the filters removes it.
            if (this.sortBy === 'ticket_asc' || this.sortBy === 'ticket_desc') {
                this.sortBy = 'submission_asc';
            }
        },

        // The Target DOJ filter calendar.
        //
        // Built the same way as the allotment calendar in the drawer: every date
        // is selectable and the dates an administrator approved for the cycle
        // are highlighted. Two deliberate differences -- there is no minimum
        // date, because a filter is normally used to look BACKWARDS at people
        // who have already joined, and the highlight follows the cycle filter
        // rather than one candidate's cycle.
        initQueueDojFilterCalendar(element) {
            if (!element) return;
            if (element._flatpickr) element._flatpickr.destroy();
            const fp = flatpickr(element, {
                dateFormat: 'Y-m-d', altInput: true, altFormat: 'd-m-Y',
                allowInput: false,
                defaultDate: this.filters.specificDoj || null,
                onDayCreate: (dObj, dStr, fpObj, dayElem) => {
                    const y = dayElem.dateObj.getFullYear();
                    const m = String(dayElem.dateObj.getMonth() + 1).padStart(2, '0');
                    const d = String(dayElem.dateObj.getDate()).padStart(2, '0');
                    if (this.queueApprovedDojDates.includes(`${y}-${m}-${d}`)) {
                        dayElem.classList.add('ahr-approved-date');
                    }
                },
                onChange: (dates, str) => { this.filters.specificDoj = str || ''; }
            });
            this.fpInstances.push(fp);
        },

        clearQueueDojFilter() {
            this.filters.specificDoj = '';
            const el = document.getElementById('queueDojFilter');
            if (el && el._flatpickr) el._flatpickr.clear();
        },

        // The header tick box selects WHAT IS ON SCREEN. It used to select every
        // record matching the filters, which with paging would mean ticking a
        // box above 25 rows and selecting three hundred.
        toggleAllRows(event, context = 'queue') {
            if (context === 'queue') this.selectedRows = event.target.checked ? this.pagedQueue.map(app => app.ticket) : [];
            else if (context === 'offers') this.selectedRows = event.target.checked ? this.pendingOffers.map(app => app.ticket) : [];
            else if (context === 'certificates') this.selectedRows = event.target.checked ? this.pendingCertificates.map(app => app.ticket) : [];
        },

        bulkAction(actionType) {
            if (this.selectedRows.length === 0) return;
            alert(`[AUDIT LOG] System Event Simulated:\nBulk Workflow [${actionType}] applied to ${this.selectedRows.length} candidates.`);
            this.selectedRows = []; 
        },
        
        // Mass Sign & Activate. The whole batch is attempted: one application
        // with a missing sub-department does not stop the other nineteen, and
        // anything that fails comes back with its reason so HR-OPS can put it
        // right and re-issue.
        async bulkSignAndIssue(docType) {
            if (this.selectedRows.length === 0) return;

            if (docType !== 'Offer Letter') {
                alert(`${docType} generation is not implemented yet.`);
                return;
            }
            if (!this.signatoryDetails.canIssue) {
                alert('You have no approved signature, so no letter can be issued.\n\nUpload one from the Authorization & Issuance panel and ask a system administrator to approve it.');
                return;
            }
            if (!confirm(`Sign and issue ${this.selectedRows.length} offer letter(s)?\n\nEach one is stamped with your approved signature.`)) return;

            const tickets = [...this.selectedRows];
            this.selectedRows = [];
            await this.issueOfferLetters(tickets);
        },

        triggerBulkNoShow() {
            this.bulkNoShowData.flagged = [];
            this.bulkNoShowData.rejected = [];
            this.selectedRows.forEach(ticket => {
                const app = this.applications.find(a => a.ticket === ticket);
                if (app.hasUsedDojLifeline) this.bulkNoShowData.rejected.push(ticket);
                else this.bulkNoShowData.flagged.push(ticket);
            });
            new bootstrap.Modal(document.getElementById('bulkNoShowModal')).show();
        },

        async confirmBulkNoShow() {
            alert(`[AUDIT LOG] System Event Simulated:\nBulk No-Show Processed.\n- Flagged: ${this.bulkNoShowData.flagged.length}\n- Rejected: ${this.bulkNoShowData.rejected.length}`);
            this.selectedRows = [];
            bootstrap.Modal.getInstance(document.getElementById('bulkNoShowModal')).hide();
        },

        // Actions that push an application back to the referrer for a document
        // correction. The referrer only sees the remark, so without one they are
        // told to fix something without being told what.
        CORRECTION_ACTIONS: ['Document Correction', 'Returned for Correction'],

        async confirmAction(action) {
            if (!this.selectedApplicant) return;

            // THE REMARK BOX'S CONFIRM BUTTON ALWAYS SENDS THE SAME ACTION.
            //
            // It calls confirmAction('Returned for Correction') whatever opened
            // it. So a return that had already routed itself -- the clearance
            // return, the corrected-letter return -- came back through here as a
            // generic correction and fell into the REJECTION path: the
            // application was rejected and pushed to the referrer, which is
            // exactly what HR-APP saw.
            //
            // pendingActionType records which button actually opened the box, so
            // the decision is sent back where it belongs before anything else
            // gets a chance to interpret it.
            if (this.pendingActionType === 'Return Clearance') {
                this.showRemarkInput = false;
                await this.returnClearance();
                return;
            }
            if (this.pendingActionType === 'Return Corrected Letter') {
                this.showRemarkInput = false;
                await this.decideOfferCorrection('reject');
                return;
            }

            // A correction request MUST carry a reason. Enforced on the server
            // too -- this check exists to give immediate feedback rather than a
            // round trip, not as the guarantee.
            if (this.CORRECTION_ACTIONS.includes(action) && !(this.actionRemark || '').trim()) {
                alert('Please enter a remark explaining what the referrer needs to correct. '
                      + 'This is what they will see, so be specific.');
                this.showRemarkInput = true;
                this.$nextTick(() => {
                    const box = document.getElementById('actionRemarkInput');
                    if (box) box.focus();
                });
                return;
            }

            let logMsg = `[AUDIT LOG] System Event:\nActor: ${this.roleNames[this.currentRole]} [${this.currentRole}]\nAction: [${action}]\nTarget: ${this.selectedApplicant.ticket}`;
            if (this.showRemarkInput && this.actionRemark.trim() !== '') logMsg += `\nRemarks: "${this.actionRemark}"`;
            
            let newStatus = this.selectedApplicant.status;
            if (action === 'Apply Fixes & Re-Submit') newStatus = 'Under Verification';
            if (action === 'Schedule') newStatus = 'Scheduled';
            if (action === 'Return to Operator') {
                // Pending Offer Re-Approval is handled above, by the correction
                // loop. It must NOT come here: the joining details are fine, it
                // is the uploaded letter that has to be re-done, and that goes
                // back to Offer Ready rather than into the Fix Joining queue.
                if(this.selectedApplicant.status === 'Pending Offer Letter') newStatus = 'Fix Joining';
                if(this.selectedApplicant.status === 'Pending Certificate') newStatus = 'Fix Clearance';
            }
            // FIX JOINING, PUT RIGHT.
            //
            // Where it goes back to depends on how far the candidate had got.
            // Fix Joining is reachable from two places: from Scheduled, when the
            // joining date is wrong before the candidate turns up, and from
            // Pending Offer Letter, when HR-APP refuses to sign because the
            // posting is wrong. Sending both back to Scheduled would un-arrive
            // an intern who is already sitting in the building.
            //
            // Arrival is the boundary, and actualDoj is the record of it.
            //
            // The button used to call confirmAction('Scheduled'), which matched
            // no branch here at all -- the resolver tests for 'Schedule' -- so
            // the status silently stayed Fix Joining and the button appeared to
            // do nothing.
            if (action === 'Joining Fixes Applied') {
                newStatus = this.selectedApplicant.actualDoj ? 'Pending Offer Letter' : 'Scheduled';
            }
            if (action === 'Clearance Requested Fix') newStatus = 'Pending Certificate';
            if (action === 'Arrival Confirmed') {
                newStatus = 'Pending Offer Letter';
                this.selectedApplicant.actualDoj = this.selectedApplicant.allottedDoj; 
            }
            if (action === 'Rejected') {
                newStatus = 'Rejected';
                if(this.selectedApplicant.isAdminEscalated) this.selectedApplicant.isAdminEscalated = false;
            }

            // --- REFERRER BOUNCE-BACK ---
            // These actions push the application back to the referrer rather than
            // rejecting it outright. bounceCategory tells the server to park it as
            // Rejected AND set awaiting_referrer_action, so it shows in the HR
            // Rejected tab while remaining actionable in the referrer portal.
            // Without this the server treats it as a final rejection and the
            // application never returns to the referrer.
            let bounceCategory = null;
            // AT PENDING OFFER RE-APPROVAL, the correction loop owns this.
            //
            // A raw status change here would be wrong twice over: it would send
            // the application somewhere without rejecting the uploaded file, so
            // the corrected letter would stay sitting in the approval queue
            // while the application had moved on -- and the loop's own endpoint
            // is what quarantines that file and records the reason HR-OPS is
            // shown. So this delegates instead of deciding.
            if ((action === 'Document Correction' || action === 'Returned for Correction'
                 || action === 'Return to Operator')
                && this.selectedApplicant.status === 'Pending Offer Re-Approval') {
                await this.decideOfferCorrection('reject');
                return;
            }

            if (action === 'Document Correction' || action === 'Returned for Correction') {
                // WHERE it goes back to depends on WHAT is wrong.
                //
                // At Pending Offer Letter, HR-APP is refusing to sign because
                // the joining logistics are wrong -- the sub-department, the
                // date. Those belong to HR-OPS. Sending it to the referrer as a
                // rejection was doubly wrong: it closed a perfectly good
                // application, and it asked the one person who cannot change
                // either field to fix them.
                //
                // Everywhere else the action still means a DOCUMENT problem,
                // which is the referrer's to put right.
                if (this.selectedApplicant.status === 'Pending Offer Letter') {
                    newStatus = 'Fix Joining';
                } else {
                    bounceCategory = 'Invalid Document';
                    newStatus = 'Rejected';
                }
            }
            
            this.selectedApplicant.status = newStatus;
            if (bounceCategory) {
                this.selectedApplicant.awaitingReferrerAction = true;
                this.selectedApplicant.rejectionCategory = bounceCategory;
            }
            
            // FIRE TO TI-DB CLOUD
            await this.syncActionToCloud({
                ticket: this.selectedApplicant.ticket,
                status: newStatus,
                bounceCategory: bounceCategory,
                remark: this.actionRemark,
                allottedDoj: this.selectedApplicant.allottedDoj,
                subDepartment: this.selectedApplicant.subDepartment,
                isAdminEscalated: this.selectedApplicant.isAdminEscalated
            });

            alert(logMsg);
            this.showRemarkInput = false;
            this.actionRemark = '';
            let offcanvas = bootstrap.Offcanvas.getInstance(document.getElementById('applicantDrawer'));
            if(offcanvas) offcanvas.hide();
        },

        openApplicantDrawer(ticketId) {
            this.selectedApplicant = null;
            // Cleared on every open: a marker left over from a previous
            // application would send this one's return down the wrong path.
            this.pendingActionType = '';
            this.showRemarkInput = false;
            this.actionRemark = '';
            if (this.fpInstances) {
                this.fpInstances.forEach(fp => { if(fp) fp.destroy(); });
                this.fpInstances = [];
            }

            this.$nextTick(() => {
                let isArchived = false;
                this.selectedApplicant = this.applications.find(a => a.ticket === ticketId);

                // College Referrals records are held separately -- the server
                // keeps them out of the main queue until they are merged.
                if (!this.selectedApplicant) {
                    this.selectedApplicant = this.collegeReferrals.find(a => a.ticket === ticketId);
                    // Put a stored degree or branch back into its dropdown, so a
                    // custom value shows as "Other" plus its text rather than
                    // rendering blank and being wiped on the next save.
                    if (this.selectedApplicant) this.seedIntakeEdits();
                }

                // NOT SEARCHED HERE ANY MORE. `archivedApplications` holds one
                // page of twenty-five rows, so this found a record only if it
                // happened to be on the page in view -- and the row it found
                // carries nine columns, not the sixty the drawer reads.
                //
                // Archived records are opened by openArchivedRecord(), which
                // fetches the full record and sets isArchivedRecord from the
                // server's answer.

                // Nothing matched. Better to say so than to throw on the next
                // line and leave the drawer half-open with stale contents.
                if (!this.selectedApplicant) {
                    console.error('No application found for ticket', ticketId);
                    alert('That application could not be loaded. Refresh the page and try again.');
                    return;
                }
                
                this.selectedApplicant.isArchivedRecord = isArchived;
                
                if (!this.selectedApplicant.allottedDoj) this.selectedApplicant.allottedDoj = this.selectedApplicant.doj;
                this.subDeptSearchQuery = this.selectedApplicant.subDepartment || '';
                this.showSubDeptDropdown = false;
                this.showRemarkInput = false;
                this.actionRemark = '';
                this.pendingActionType = '';
                
                this.customOverrideFile = this.selectedApplicant.customOverrideFile || null;
                this.tempDmraDate = this.selectedApplicant.dmraSessionDate || null;
                this.selectedApplicant.hardCopyUndertaking = false;
                this.selectedApplicant.hardCopyAttendance = false;
                
                this.adminEditMode = false;
                this.adminModeStatus = '';
                this.adminModeRemark = '';
                this.adminSnapshot = null;
                this.adminPendingChanges = [];
                this.adminWarnings = null;

                const offcanvasEl = document.getElementById('applicantDrawer');
                let offcanvas = bootstrap.Offcanvas.getInstance(offcanvasEl);
                if (!offcanvas) offcanvas = new bootstrap.Offcanvas(offcanvasEl);
                offcanvas.show();
                
                // Initialize all dynamic calendars securely after DOM stamp
                setTimeout(() => {
                    const appDoj = document.getElementById('approvedDojCalendar');
                    const escDoj = document.getElementById('escalationDojCalendar');
                    const fixDoj = document.getElementById('fixJoiningDojCalendar');
                    const pjDoj = document.getElementById('pendingJoiningDojCalendar');
                    const dmraCal = document.getElementById('dmraCalendar');
                    
                    if (appDoj) this.initCalendar(appDoj);
                    if (escDoj) this.initCalendar(escDoj);
                    if (fixDoj) this.initCalendar(fixDoj);
                    if (pjDoj) this.initCalendar(pjDoj);
                    if (dmraCal) this.initDmraCalendar(dmraCal);
                }, 100);
                
                // Initialize flatpickr on God Mode state trackers
                this.$watch('adminEditMode', (val) => {
                    if(val) {
                        setTimeout(() => {
                            let currentDojVal = this.getDisplayDojValue(this.selectedApplicant);
                            let gmDoj = document.getElementById('godModeDoj');
                            if (gmDoj) {
                                let fpDoj = flatpickr(gmDoj, { 
                                    dateFormat: 'Y-m-d',
                                    defaultDate: currentDojVal, 
                                    onDayCreate: (dObj, dStr, fpObj, dayElem) => {
                                        let y = dayElem.dateObj.getFullYear();
                                        let m = String(dayElem.dateObj.getMonth() + 1).padStart(2, '0');
                                        let d = String(dayElem.dateObj.getDate()).padStart(2, '0');
                                        if (this.getCycleDojDates().includes(`${y}-${m}-${d}`)) dayElem.classList.add('ahr-approved-date');
                                    },
                                    onChange: (d, s) => {
                                        if (['Scheduled', 'Pending Offer Letter', 'Fix Joining', 'Offer Ready', 'Pending Offer Re-Approval', 'Pending Arrival', 'Ready for Merge'].includes(this.selectedApplicant.status)) {
                                            this.selectedApplicant.allottedDoj = s;
                                        } else if (['Joined', 'Fix Clearance', 'Pending Certificate', 'Pending Dispatch', 'Completed'].includes(this.selectedApplicant.status)) {
                                            this.selectedApplicant.actualDoj = s;
                                        } else {
                                            this.selectedApplicant.doj = s;
                                        }
                                    } 
                                });
                                this.fpInstances.push(fpDoj);
                            }

                            let gmDob = document.getElementById('godModeDob');
                            if (gmDob) {
                                let fpDob = flatpickr(gmDob, {
                                    dateFormat: 'Y-m-d',
                                    altInput: true,
                                    altFormat: 'd-m-Y',
                                    maxDate: 'today', 
                                    defaultDate: this.selectedApplicant.bio.dob,
                                    onChange: (d, s) => {
                                        this.selectedApplicant.bio.dob = s;
                                    }
                                });
                                this.fpInstances.push(fpDob);
                            }
                        }, 50);
                    }
                });
            });
        },

        // True when the record is still inside the College Referrals section.
        // Drives which action block the drawer shows.
        isCollegeReferral(app) {
            const a = app || this.selectedApplicant;
            return !!a && a.referralSource === 'Institutional'
                   && ['Intake Draft', 'Pending Arrival', 'Ready for Merge'].includes(a.status);
        },

        isNonStandardDoj() {
            if (!this.selectedApplicant || !this.selectedApplicant.allottedDoj) return false;
            return !this.getCycleDojDates().includes(String(this.selectedApplicant.allottedDoj).trim());
        },

        initCalendar(element) {
            if (!element) return;
            if (element._flatpickr) { element._flatpickr.destroy(); }
            
            let isReadOnly = ['Pending Offer Letter'].includes(this.selectedApplicant.status) || this.selectedApplicant.isArchivedRecord;
            
            let fp = flatpickr(element, {
                dateFormat: 'Y-m-d', altInput: true, altFormat: 'd-m-Y', minDate: 'today',
                defaultDate: this.selectedApplicant.allottedDoj || this.selectedApplicant.doj,
                clickOpens: !isReadOnly, 
                onDayCreate: (dObj, dStr, fpObj, dayElem) => {
                    let y = dayElem.dateObj.getFullYear();
                    let m = String(dayElem.dateObj.getMonth() + 1).padStart(2, '0');
                    let d = String(dayElem.dateObj.getDate()).padStart(2, '0');
                    if (this.getCycleDojDates().includes(`${y}-${m}-${d}`)) dayElem.classList.add('ahr-approved-date');
                },
                onChange: (selectedDates, str) => {
                    this.selectedApplicant.allottedDoj = str || null;
                }
            });
            this.fpInstances.push(fp);
        },

        triggerRemarkAction(actionType, autoFillContext = null) {
            this.pendingActionType = actionType;
            this.showRemarkInput = true;
            if (autoFillContext === 'Repeated DOJ') this.actionRemark = 'REPEATED NO-SHOW. LIFELINE EXHAUSTED.';
            else this.actionRemark = '';
        },

        cancelRemarkAction() {
            this.showRemarkInput = false;
            this.actionRemark = '';
            this.pendingActionType = '';
        },

        // Signs and issues the offer letter for the open application.
        //
        // The SERVER decides whether it may be issued and says why not. This
        // used to set the status locally and show an alert claiming success,
        // so a letter that could never have been produced still appeared to
        // have been.
        async generateDocument(docType) {
            if (!this.selectedApplicant) return;

            if (docType === 'Approve Custom Offer') {
                await this.decideOfferCorrection('approve');
                return;
            }
            if (docType !== 'Offer Letter') {
                // The completion certificate is not built yet. Say so plainly
                // rather than pretending the action worked.
                alert(`${docType} generation is not implemented yet.`);
                return;
            }

            await this.issueOfferLetters([this.selectedApplicant.ticket]);
            this.closeDrawer();
        },

        // Shared by the single-application button and Mass Sign & Activate.
        // Each application is issued independently on the server, so one that
        // cannot be issued never blocks the rest.
        async issueOfferLetters(tickets) {
            if (!tickets || tickets.length === 0) return;
            try {
                const response = await fetch('http://127.0.0.1:8000/api/offer-letters/issue/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ tickets })
                });
                const data = await response.json();

                let message = data.message || '';
                if (data.failed && data.failed.length) {
                    message += '\n\nCould not be issued:\n' +
                        data.failed.map(f => `  ${f.ticket}\n     ${f.reason}`).join('\n');
                }
                alert(message || 'No response from the server.');
            } catch (err) {
                console.error('Offer letter issuance failed:', err);
                alert('Offer letters could not be issued: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },

        // --- THE COMPLETION CERTIFICATE ------------------------------------

        // HR-APP issues, one application or a selected batch. Each is issued
        // independently on the server, so one incomplete clearance never
        // silently undoes the rest.
        async issueCertificates(tickets) {
            if (!tickets || !tickets.length) return;
            try {
                const response = await fetch('http://127.0.0.1:8000/api/certificates/issue/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ tickets })
                });
                const data = await response.json();
                let message = data.message || '';
                if (data.failed && data.failed.length) {
                    message += '\n\nCould not be issued:\n'
                             + data.failed.map(f => `  ${f.ticket}\n     ${f.reason}`).join('\n');
                }
                alert(message || 'No response from the server.');
            } catch (err) {
                console.error('Certificate issuance failed:', err);
                alert('Certificates could not be issued: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },

        // Returns the clearance to HR-OPS. Everything already recorded is kept;
        // the reason is the only thing telling them what to fix.
        async returnClearance() {
            if (!this.selectedApplicant) return;
            const reason = (this.actionRemark || '').trim().toUpperCase();
            if (!reason) {
                this.showRemarkInput = true;
                this.pendingActionType = 'Return Clearance';
                alert('Please enter a remark explaining what is wrong. It is all HR-OPS receives.');
                this.$nextTick(() => {
                    const box = document.getElementById('actionRemarkInput');
                    if (box) box.focus();
                });
                return;
            }
            try {
                const response = await fetch('http://127.0.0.1:8000/api/certificates/issue/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ ticket: this.selectedApplicant.ticket, reason })
                });
                const data = await response.json();
                if (!response.ok) { alert(data.error || 'The clearance could not be returned.'); return; }
                alert(data.message);
                this.showRemarkInput = false;
                this.actionRemark = '';
                this.pendingActionType = '';
                this.closeDrawer();
            } catch (err) {
                console.error('Clearance return failed:', err);
                alert('The clearance could not be returned: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },

        // Opens the certificate in a new tab, or downloads the Word copy.
        // Same reasoning as the offer letter: the PDF is DMRC's own document
        // and is meant to be read and printed, so it opens rather than being
        // forced to download -- and every open is still logged.
        async viewCertificate(variant) {
            if (!this.selectedApplicant) return;

            // Same as downloadOfferLetter: an archived certificate is served
            // from the file that was issued, because the live application row
            // it would otherwise be rebuilt from no longer exists.
            if (this.selectedApplicant.isArchivedRecord) {
                const stored = this.selectedApplicant.certificate;
                const href = this.documentHref(stored);
                if (!href) {
                    alert('No completion certificate is held in the archive for this record.');
                    return;
                }
                if (variant === 'docx') {
                    alert('Only the signed PDF is retained in the archive. '
                          + 'The editable Word copy is generated on demand and is not stored.');
                    return;
                }
                window.open(href, '_blank');
                setTimeout(() => this.fetchAuditLedger(), 800);
                return;
            }

            const ticket = this.selectedApplicant.ticket;
            const emp = this.identity ? this.identity.employeeCode : '';
            const url = `http://127.0.0.1:8000/api/certificates/file/?ticket=${encodeURIComponent(ticket)}`
                      + `&variant=${variant}&emp=${encodeURIComponent(emp)}`;
            if (variant === 'pdf') {
                window.open(url, '_blank');
                setTimeout(() => this.fetchAuditLedger(), 800);
                return;
            }
            try {
                const response = await fetch(url, { headers: this.authHeaders() });
                if (!response.ok) {
                    let detail = 'The file could not be downloaded.';
                    try { detail = (await response.json()).error || detail; } catch (e) {}
                    alert(detail); return;
                }
                const blob = await response.blob();
                const link = document.createElement('a');
                link.href = URL.createObjectURL(blob);
                link.download = `Completion_Certificate_${ticket}.docx`;
                document.body.appendChild(link); link.click(); document.body.removeChild(link);
                URL.revokeObjectURL(link.href);
                this.fetchAuditLedger();
            } catch (err) {
                console.error('Certificate download failed:', err);
                alert('The file could not be downloaded: the server could not be reached.');
            }
        },

        // HR-APP uploads a corrected certificate. Both ends of this loop are the
        // same person by design -- once a certificate exists, corrections belong
        // to HR-APP alone. The value is that the corrected file goes back
        // through the same door, is signed by the same mechanism, and leaves the
        // same audit trail, rather than being swapped in silently.
        async submitCertificateCorrection() {
            if (!this.selectedApplicant || !this.customOverrideFileObj) return;
            const form = new FormData();
            form.append('ticket', this.selectedApplicant.ticket);
            form.append('file', this.customOverrideFileObj);
            form.append('remark', this.actionRemark || '');
            try {
                const response = await fetch('http://127.0.0.1:8000/api/certificates/correction/', {
                    method: 'POST', headers: this.authHeaders(), body: form
                });
                const data = await response.json();
                if (!response.ok) { alert(data.error || 'The corrected certificate could not be submitted.'); return; }
                alert(data.message);
                this.customOverrideFile = null;
                this.customOverrideFileObj = null;
                this.actionRemark = '';
                this.closeDrawer();
            } catch (err) {
                console.error('Certificate correction failed:', err);
                alert('The corrected certificate could not be submitted: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },

        async decideCertificateCorrection(decision) {
            if (!this.selectedApplicant) return;
            let reason = '';
            if (decision === 'reject') {
                reason = (this.actionRemark || '').trim().toUpperCase();
                if (!reason) {
                    this.showRemarkInput = true;
                    alert('Please enter a remark explaining why this corrected certificate is being discarded.');
                    return;
                }
            }
            try {
                const response = await fetch('http://127.0.0.1:8000/api/certificates/correction/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ ticket: this.selectedApplicant.ticket, decision, reason })
                });
                const data = await response.json();
                if (!response.ok) { alert(data.error || 'The decision could not be recorded.'); return; }
                alert(data.message);
                this.actionRemark = '';
                this.closeDrawer();
            } catch (err) {
                console.error('Certificate decision failed:', err);
                alert('The decision could not be recorded: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },

        // Sends the certificate to the candidate and closes the internship.
        async dispatchCertificate() {
            if (!this.selectedApplicant) return;
            if (!confirm(`Send the completion certificate to the candidate and close ${this.selectedApplicant.ticket}?\n\n`
                       + `This marks the intern as Completed. No further action is possible afterwards.`)) return;
            try {
                const response = await fetch('http://127.0.0.1:8000/api/certificates/dispatch/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ ticket: this.selectedApplicant.ticket })
                });
                const data = await response.json();
                if (!response.ok) { alert(data.error || 'The certificate could not be dispatched.'); return; }
                alert(data.message);
                this.closeDrawer();
            } catch (err) {
                console.error('Dispatch failed:', err);
                alert('The certificate could not be dispatched: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },

        // --- OFFER LETTER DOWNLOADS ----------------------------------------
        //
        // Fetched rather than linked. In development the identity travels in a
        // request header, and a plain <a href> cannot carry one -- the download
        // would arrive as the default employee, or be refused outright.
        // Opens the signed offer letter in a NEW TAB, or downloads the Word copy.
        //
        // The PDF is deliberately NOT force-downloaded. It is DMRC's own
        // document, meant to be read, printed and circulated, so it opens in the
        // browser's own PDF viewer -- from which the reader can save or print it
        // if they want to. What still applies is the part that matters: the
        // endpoint checks the caller's role and records the access in the audit
        // ledger, exactly as it does for a candidate's identity papers.
        //
        // The Word copy stays a download, because a browser cannot display a
        // .docx -- opening it in a tab would only produce a confusing save
        // dialog, and it is downloaded to be edited, not read.
        async downloadOfferLetter(variant) {
            if (!this.selectedApplicant) return;

            // AN ARCHIVED RECORD TAKES THE STORED FILE, NOT A REGENERATED ONE.
            //
            // /api/offer-letters/file/ rebuilds the letter from the live
            // application row, and closing a cycle deletes that row -- so for an
            // archived candidate this endpoint has nothing to build from and
            // would simply fail. What survives is the signed PDF exactly as it
            // was issued, reachable through the audited viewer.
            //
            // There is no Word copy to offer. That variant is generated on
            // demand and never stored, deliberately: a signature inside a Word
            // file can be lifted in three clicks. Said plainly rather than
            // handing back an error.
            if (this.selectedApplicant.isArchivedRecord) {
                const stored = this.selectedApplicant.offerLetter;
                const href = this.documentHref(stored);
                if (!href) {
                    alert('No offer letter is held in the archive for this record.');
                    return;
                }
                if (variant === 'docx') {
                    alert('Only the signed PDF is retained in the archive. '
                          + 'The editable Word copy is generated on demand and is not stored.');
                    return;
                }
                window.open(href, '_blank');
                // Recorded server-side by the viewer; reload so the entry shows
                // without a manual refresh.
                setTimeout(() => this.fetchAuditLedger(), 800);
                return;
            }

            const ticket = this.selectedApplicant.ticket;
            const emp = this.identity ? this.identity.employeeCode : '';
            const url = `http://127.0.0.1:8000/api/offer-letters/file/?ticket=${encodeURIComponent(ticket)}`
                      + `&variant=${variant}&emp=${encodeURIComponent(emp)}`;

            if (variant === 'pdf') {
                // A plain navigation, which is why the identity travels in the
                // query string: a new tab carries no custom header.
                window.open(url, '_blank');
                // The view is recorded server-side; reload so it appears without
                // a manual refresh.
                setTimeout(() => this.fetchAuditLedger(), 800);
                return;
            }

            try {
                const response = await fetch(url, { headers: this.authHeaders() });
                if (!response.ok) {
                    let detail = 'The file could not be downloaded.';
                    try { detail = (await response.json()).error || detail; } catch (e) {}
                    alert(detail);
                    return;
                }
                const blob = await response.blob();
                const link = document.createElement('a');
                link.href = URL.createObjectURL(blob);
                link.download = `Offer_Letter_${ticket}.docx`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                URL.revokeObjectURL(link.href);
                this.fetchAuditLedger();
            } catch (err) {
                console.error('Offer letter download failed:', err);
                alert('The file could not be downloaded: the server could not be reached.');
            }
        },

        // --- THE CORRECTION LOOP -------------------------------------------
        //
        // HR-OPS uploads a corrected PDF; it waits for HR-APP. Nothing about
        // the official letter changes until that decision is taken.
        async submitOfferCorrection() {
            if (!this.selectedApplicant || !this.customOverrideFileObj) return;
            const form = new FormData();
            form.append('ticket', this.selectedApplicant.ticket);
            form.append('file', this.customOverrideFileObj);
            form.append('remark', this.actionRemark || '');
            try {
                const response = await fetch('http://127.0.0.1:8000/api/offer-letters/correction/', {
                    method: 'POST',
                    headers: this.authHeaders(),
                    body: form
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.error || 'The corrected letter could not be submitted.');
                    return;
                }
                alert(data.message);
                this.customOverrideFile = null;
                this.customOverrideFileObj = null;
                this.actionRemark = '';
                this.closeDrawer();
            } catch (err) {
                console.error('Correction upload failed:', err);
                alert('The corrected letter could not be submitted: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },

        async decideOfferCorrection(decision) {
            if (!this.selectedApplicant) return;
            // The remark comes from the drawer's own box, not a browser prompt().
            // A prompt() is unstyled, sits outside the drawer, and cannot be
            // made mandatory in any way the user can see -- and this is the only
            // explanation HR-OPS receives.
            let reason = '';
            if (decision === 'reject') {
                reason = (this.actionRemark || '').trim().toUpperCase();
                if (!reason) {
                    this.showRemarkInput = true;
                    this.pendingActionType = 'Return Corrected Letter';
                    alert('Please enter a remark explaining what is wrong with the corrected letter. '
                          + 'This is what HR-OPS will see, so be specific.');
                    this.$nextTick(() => {
                        const box = document.getElementById('actionRemarkInput');
                        if (box) box.focus();
                    });
                    return;
                }
            }
            try {
                const response = await fetch('http://127.0.0.1:8000/api/offer-letters/correction/', {
                    method: 'PATCH',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ ticket: this.selectedApplicant.ticket, decision, reason })
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.error || 'The decision could not be recorded.');
                    return;
                }
                alert(data.message);
                this.showRemarkInput = false;
                this.actionRemark = '';
                this.closeDrawer();
            } catch (err) {
                console.error('Correction decision failed:', err);
                alert('The decision could not be recorded: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },

        // --- HANDOVER -------------------------------------------------------
        //
        // The two hard-copy confirmations are stored on the server. They used
        // to live only in the browser, so they vanished on the next reload and
        // nothing recorded that the paperwork had been collected.
        async confirmOfferHandover() {
            if (!this.selectedApplicant) return;
            try {
                const response = await fetch('http://127.0.0.1:8000/api/offer-letters/handover/', {
                    method: 'POST',
                    headers: this.authHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({
                        ticket: this.selectedApplicant.ticket,
                        undertaking: !!this.selectedApplicant.hardCopyUndertaking,
                        attendance: !!this.selectedApplicant.hardCopyAttendance
                    })
                });
                const data = await response.json();
                if (!response.ok) {
                    alert(data.error || 'The handover could not be recorded.');
                    return;
                }
                alert(data.message);
                this.closeDrawer();
            } catch (err) {
                console.error('Handover failed:', err);
                alert('The handover could not be recorded: the server could not be reached.');
            } finally {
                await this.refreshAfterAction();
            }
        },

        // Reload the queue and re-point the open drawer at the refreshed
        // record, so a status change is visible without closing and reopening.
        async refreshAfterAction() {
            const openTicket = this.selectedApplicant ? this.selectedApplicant.ticket : null;
            await this.fetchLiveQueue();
            this.fetchAuditLedger();
            if (openTicket) {
                const refreshed = this.applications.find(a => a.ticket === openTicket);
                if (refreshed) this.selectedApplicant = refreshed;
            }
        },

        closeDrawer() {
            const offcanvas = bootstrap.Offcanvas.getInstance(document.getElementById('applicantDrawer'));
            if (offcanvas) offcanvas.hide();
        },

        // NOTE: uploadSignature() used to be defined HERE as well as above. Two
        // methods of the same name in one object literal is legal JavaScript --
        // the last one silently wins -- so the real upload never ran and
        // choosing a file appeared to do nothing at all. Do not re-add it.
    }));
});