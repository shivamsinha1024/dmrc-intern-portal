/**
 * DMRC INTERN REFERRAL WIZARD — RELEASABLE APPS ENGINE
 * Powered natively by Alpine.js reactive state architecture.
 */
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
        
        // God Mode State
        adminEditMode: false,
        adminModeStatus: '',
        adminModeRemark: '',
        adminOrigDept: '',
        adminOrigWard: false,

        // --- NEW: FORENSIC, ARCHIVE VAULT & AUDIT EXPORT STATE ---
        forensicData: { ticket: null, isLoading: false, candidateUploads: [], officialDocuments: [] },
        archiveSearch: '',
        archiveYear: '',
        archiveCycle: '',
        isExportingQueue: false,
        isExporting: false,
        isExportingAudit: false,
        archivedApplications: [],
        selectedArchive: null,

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

        // Everything in an archived cycle is finished, so the useful cuts differ
        // from the live queue: outcome and reason rather than stage.
        archiveFilters: { outcome: '', department: '', subDepartment: '',
                          rejectionCategory: '', source: '',
                          ward: false, waitlisted: false, noShow: false },
        archiveSort: { key: 'ticket', dir: 'asc' },

        get filteredArchives() {
            if (!this.archiveCycle) return [];
            let result = this.archivedApplications.filter(app => app.cycle === this.archiveCycle);

            const f = this.archiveFilters;
            if (f.outcome) result = result.filter(a => a.status === f.outcome);
            if (f.department) result = result.filter(a => a.department === f.department);
            if (f.subDepartment) result = result.filter(a => a.subDepartment === f.subDepartment);
            if (f.rejectionCategory) result = result.filter(a => a.rejectionCategory === f.rejectionCategory);
            if (f.source) result = result.filter(a => a.referralSource === f.source);
            if (f.ward) result = result.filter(a => a.ward === true);
            if (f.waitlisted) result = result.filter(a => a.waitlisted === true);
            if (f.noShow) result = result.filter(a => a.noShow === true);

            // Search runs AFTER the filters, narrowing what is on screen.
            if (this.archiveSearch.trim() !== '') {
                const q = this.archiveSearch.toUpperCase();
                const hit = v => (v || '').toString().toUpperCase().includes(q);
                result = result.filter(a =>
                    hit(a.ticket) || hit(a.name) || hit(a.department) ||
                    hit(a.subDepartment) || hit(a.academic && a.academic.college) ||
                    hit(a.referrerName)
                );
            }

            // Sorted last, so what is on screen is exactly what exports.
            const { key, dir } = this.archiveSort;
            const mult = dir === 'desc' ? -1 : 1;
            result = [...result].sort((a, b) => {
                // Dates are compared in ISO form, and BLANKS ALWAYS SINK to the
                // bottom regardless of direction: a rejected candidate never
                // joined and never completed, and scattering those empties
                // through the dated records makes the list unreadable.
                if (key === 'doj' || key === 'completion') {
                    const av = key === 'doj' ? a.dojRaw : a.completionRaw;
                    const bv = key === 'doj' ? b.dojRaw : b.completionRaw;
                    if (!av && !bv) return 0;
                    if (!av) return 1;
                    if (!bv) return -1;
                    return av < bv ? -1 * mult : av > bv ? 1 * mult : 0;
                }
                const av = (a[key] || '').toString().toUpperCase();
                const bv = (b[key] || '').toString().toUpperCase();
                if (!av && !bv) return 0;
                if (!av) return 1;
                if (!bv) return -1;
                return av < bv ? -1 * mult : av > bv ? 1 * mult : 0;
            });

            return result;
        },

        setArchiveSort(key) {
            if (this.archiveSort.key === key) {
                this.archiveSort.dir = this.archiveSort.dir === 'asc' ? 'desc' : 'asc';
            } else {
                this.archiveSort = { key: key, dir: 'asc' };
            }
        },

        resetArchiveFilters() {
            this.archiveFilters = { outcome: '', department: '', subDepartment: '',
                                    rejectionCategory: '', source: '',
                                    ward: false, waitlisted: false, noShow: false };
            this.archiveSearch = '';
        },

        // Only the departments and units that actually appear in this cycle's
        // archive. Offering the current live lists would suggest options that
        // match nothing, since both change over the years.
        get archiveDepartmentOptions() {
            const set = new Set(this.archivedApplications
                .filter(a => a.cycle === this.archiveCycle)
                .map(a => a.department).filter(Boolean));
            return [...set].sort();
        },

        get archiveSubDeptOptions() {
            const set = new Set(this.archivedApplications
                .filter(a => a.cycle === this.archiveCycle)
                .map(a => a.subDepartment).filter(Boolean));
            return [...set].sort();
        },

        // The columns on screen, in order. The export sends this list, so the
        // file always has the same shape as the view it came from.
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
        
        masterSearch: '',
        // The College Referrals pipeline has its own search box, so a term
        // typed there does not silently filter the other queue as well.
        referralSearch: '',
        isExportingReferrals: false,
        filters: { 
            cycle: '', department: '', subDepartment: '', specificDoj: '', evaluationResult: '', 
            resubmissionType: '', dmraStatus: '', isWaitlisted: false, isWard: false, isCritical: false, 
            hasCustomOverride: false 
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
            this.$watch('archiveCycle', () => { this.fetchArchives(); });

            this.$watch('adminSelectedCycle', async (name) => {
                if (!name) return;
                await this.fetchAdminConfigs();
                await this.fetchAdminCycles();
            });
            this.$watch('adminEditMode', (val) => {
                if(val && this.selectedApplicant) {
                    this.adminOrigDept = this.selectedApplicant.department;
                    this.adminOrigWard = this.selectedApplicant.ward;
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

        async fetchArchives() {
            try {
                const params = new URLSearchParams();
                if (this.archiveCycle) {
                    const parts = this.archiveCycle.split(' ');
                    params.set('term', parts[0]);
                    params.set('year', parts[1]);
                } else if (this.archiveYear) {
                    params.set('year', this.archiveYear);
                }

                const response = await fetch(
                    `http://127.0.0.1:8000/api/hr/archives/?${params.toString()}`,
                    { headers: this.authHeaders() });

                if (!response.ok) {
                    if (response.status !== 403) console.error("GET Archives failed:", response.status);
                    this.archivedApplications = [];
                    return;
                }
                const data = await response.json();
                this.archivedApplications = data.records || [];
                this.archiveYearsAvailable = data.availableYears || [];
                this.archiveCyclesByYear = data.cyclesByYear || {};
            } catch (error) {
                console.error("Network error fetching Archives:", error);
                // Left empty rather than falling back to specimen data: an
                // empty vault is honest, invented records are not.
                this.archivedApplications = [];
            }
        },

        // Opens the read-only drawer for one archived candidate. The record is
        // already loaded, so there is no second request and nothing to fail
        // halfway.
        openArchivedRecord(ticket) {
            const record = this.archivedApplications.find(a => a.ticket === ticket);
            if (!record) {
                alert('That record could not be found. Reload the archive and try again.');
                return;
            }
            this.selectedArchive = record;
            new bootstrap.Offcanvas(document.getElementById('archiveDrawer')).show();
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
        getDisplayDojValue(app) {
            if (!app) return '';
            if (['Scheduled', 'Pending Offer Letter', 'Fix Joining', 'Offer Ready', 'Pending Offer Re-Approval', 'Pending Arrival', 'Ready for Merge'].includes(app.status)) return app.allottedDoj;
            if (['Joined', 'Fix Clearance', 'Pending Certificate', 'Pending Dispatch', 'Completed'].includes(app.status)) return app.actualDoj;
            return app.doj;
        },
        getTabDojHeader(tab) {
            if (['All', 'Resubmissions', 'Rejected'].includes(tab)) return 'Date of Joining';
            if (['Scheduled', 'Pending Offer Letter', 'Fix Joining', 'Ready for Handover'].includes(tab)) return 'Allotted DOJ';
            if (['Active', 'Fix Clearance', 'Pending Certificate', 'Completed'].includes(tab)) return 'Actual DOJ';
            return 'Requested DOJ'; 
        },

        // --- UNIVERSAL WYSIWYG EXPORT ENGINE ---
        async executeExport(moduleType, format) {
            let payloadIds = [];
            let fileName = `DMRC_Export_${moduleType}_${new Date().toISOString().split('T')[0]}`;

            // Extract precisely filtered IDs based on the active screen context
            if (moduleType === 'queue') {
                this.isExportingQueue = true;
                payloadIds = this.processedQueue.map(app => app.ticket);
                fileName = `DMRC_Active_Queue_${new Date().toISOString().split('T')[0]}`;
            } else if (moduleType === 'archive') {
                this.isExporting = true;
                payloadIds = this.filteredArchives.map(app => app.ticket);
                let deptStr = this.filters.department ? `_${this.filters.department}` : '_AllDepts';
                fileName = `DMRC_Archive_${this.archiveCycle.replace(' ', '')}${deptStr}`;
            } else if (moduleType === 'college') {
                this.isExportingReferrals = true;
                payloadIds = this.filteredCollegeReferrals.map(a => a.ticket);
                fileName = `DMRC_College_Referrals_${new Date().toISOString().split('T')[0]}`;
            } else if (moduleType === 'audit') {
                this.isExportingAudit = true;
                payloadIds = this.filteredAuditLogs.map(log => log.logId);
                fileName = `DMRC_Audit_Ledger_${new Date().toISOString().split('T')[0]}`;
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
                        columns: moduleType === 'archive' ? this.archiveColumns : undefined
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
                
                // Only log exports of PII (Queue/Archives), avoid infinite loops logging the Audit log itself
                if(moduleType !== 'audit') {
                    this.auditLogs.unshift({
                        logId: Date.now(),
                        timestamp: new Date().toLocaleString(),
                        actor: `${this.roleNames[this.currentRole]} [${this.currentRole}]`,
                        category: 'SYSTEM_EXPORT',
                        target: `Module: ${moduleType.toUpperCase()}`,
                        details: `Exported ${payloadIds.length} records to ${format.toUpperCase()}.`
                    });
                }

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
            if (!this.archiveCycle || this.filteredArchives.length === 0) { alert("No records in current view to export."); return; }
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
        
        // --- GOD MODE OVERRIDE ---
        triggerGodModeExecution() {
            if(!this.adminModeRemark.trim()) return;
            new bootstrap.Modal(document.getElementById('godModeWarningModal')).show();
        },

        async confirmGodMode() {
            if (this.adminOrigDept !== this.selectedApplicant.department) {
                let oldC = this.adminCapacities.find(c => c.dept === this.adminOrigDept);
                let newC = this.adminCapacities.find(c => c.dept === this.selectedApplicant.department);
                if (oldC && !this.adminOrigWard) oldC.occupied--;
                if (newC && !this.selectedApplicant.ward) newC.occupied++;
            } else if (this.adminOrigWard !== this.selectedApplicant.ward) {
                let c = this.adminCapacities.find(c => c.dept === this.selectedApplicant.department);
                if (c) {
                    if (this.selectedApplicant.ward) c.occupied--; 
                    else c.occupied++; 
                }
            }
            
            if(this.adminModeStatus) this.selectedApplicant.status = this.adminModeStatus;
            
            // FIRE TO TI-DB CLOUD WITH GOD MODE FLAG
            await this.syncActionToCloud({
                ticket: this.selectedApplicant.ticket,
                status: this.selectedApplicant.status,
                remark: this.adminModeRemark,
                department: this.selectedApplicant.department,
                ward: this.selectedApplicant.ward,
                dob: this.selectedApplicant.bio.dob,
                isGodMode: true
            });
            
            bootstrap.Modal.getInstance(document.getElementById('godModeWarningModal')).hide();
            let offcanvas = bootstrap.Offcanvas.getInstance(document.getElementById('applicantDrawer'));
            if(offcanvas) offcanvas.hide();

            this.adminModeStatus = '';
            this.adminModeRemark = '';
            this.adminEditMode = false;
        },

        // --- NEW: FETCH FORENSIC DOCUMENTS LOGIC ---
        fetchForensicDocuments(ticketId, isArchived) {
            this.forensicData.ticket = ticketId;
            this.forensicData.isLoading = true;
            this.forensicData.candidateUploads = [];
            this.forensicData.officialDocuments = [];
            
            let app = this.applications.find(a => a.ticket === ticketId);
            if (!app) app = this.archivedApplications.find(a => a.ticket === ticketId);

            let modal = new bootstrap.Modal(document.getElementById('forensicDocumentModal'));
            modal.show();

            // Dynamic Live Backend URL Construction
            const baseURL = 'http://127.0.0.1:8000/media/';

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
        calculateCompletionDate(dojStr, internshipObj) {
            if (!dojStr) return '—';
            let parts = dojStr.split('-');
            if(parts.length !== 3) return dojStr; 
            let date = new Date(parts[0], parts[1] - 1, parts[2]);
            let weeks = 4;
            if (internshipObj && internshipObj.duration) {
                let match = internshipObj.duration.match(/\d+/);
                if (match) weeks = parseInt(match[0]);
            }
            date.setDate(date.getDate() + (weeks * 7));
            let y = date.getFullYear();
            let m = String(date.getMonth() + 1).padStart(2, '0');
            let d = String(date.getDate()).padStart(2, '0');
            return `${y}-${m}-${d}`; 
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
            if (this.filters.specificDoj) result = result.filter(app => app.doj === this.filters.specificDoj);
            if (this.filters.evaluationResult) result = result.filter(app => app.evaluationResult === this.filters.evaluationResult);
            if (this.filters.isWaitlisted) result = result.filter(app => app.waitlisted === true);
            if (this.filters.isWard) result = result.filter(app => app.ward === true);
            if (this.filters.resubmissionType === 'Document') result = result.filter(app => app.hasUsedDocumentLifeline);
            if (this.filters.resubmissionType === 'DOJ') result = result.filter(app => app.hasUsedDojLifeline);
            if (this.filters.isCritical) result = result.filter(app => app.hasUsedDocumentLifeline && app.hasUsedDojLifeline);
            if (this.filters.hasCustomOverride) result = result.filter(app => app.customOverrideFile !== null);

            if (this.filters.dmraStatus) {
                if (this.filters.dmraStatus === 'Awaiting Schedule') result = result.filter(app => !app.dmraSessionDate);
                else if (this.filters.dmraStatus === 'Scheduled') result = result.filter(app => app.dmraSessionDate && !app.dmraAttended);
                else if (this.filters.dmraStatus === 'Attended') result = result.filter(app => app.dmraAttended === 'true');
                else if (this.filters.dmraStatus === 'Missed') result = result.filter(app => app.dmraAttended === 'false');
            }

            if (this.masterSearch.trim() !== '') {
                const query = this.masterSearch.toUpperCase();
                result = result.filter(app => this.matchesSearch(app, query));
            }

            // Helper function for sort
            const getCompDate = (app) => {
                let d = this.calculateCompletionDate(app.actualDoj || app.allottedDoj, app.internship);
                return d === '—' ? new Date(8640000000000000) : new Date(d); // Push invalid dates to the end
            };

            return result.sort((a, b) => {
                let dateA = new Date(a.date);
                let dateB = new Date(b.date);
                if (this.sortBy === 'submission_asc') return dateA - dateB;
                if (this.sortBy === 'submission_desc') return dateB - dateA;
                if (this.sortBy === 'doj_asc') return new Date(a.doj) - new Date(b.doj);
                if (this.sortBy === 'resubmission_desc') {
                    let resubA = this.getLatestResubDate(a);
                    let resubB = this.getLatestResubDate(b);
                    let valA = resubA ? new Date(resubA) : dateA;
                    let valB = resubB ? new Date(resubB) : dateB;
                    return valB - valA;
                }
                if (this.sortBy === 'completion_asc') return getCompDate(a) - getCompDate(b);
                if (this.sortBy === 'completion_desc') return getCompDate(b) - getCompDate(a);
                if (this.sortBy === 'ticket_asc') return a.ticket.localeCompare(b.ticket);
                if (this.sortBy === 'ticket_desc') return b.ticket.localeCompare(a.ticket);
                return 0;
            });
        },

        get pendingOffers() { return this.applications.filter(a => a.status === 'Pending Offer Letter' || a.status === 'Pending Offer Re-Approval'); },
        get pendingCertificates() { return this.applications.filter(a => a.status === 'Pending Certificate'); },
        get readyForDispatch() { return this.applications.filter(a => a.status === 'Pending Dispatch'); },

        formatDate(isoString) {
            if (!isoString) return '—';
            const parts = isoString.split('-');
            if(parts.length !== 3) return isoString; 
            return `${parts[2]}-${parts[1]}-${parts[0]}`;
        },

        clearFilters() {
            this.filters = { cycle: '', department: '', subDepartment: '', specificDoj: '', evaluationResult: '', resubmissionType: '', dmraStatus: '', isWaitlisted: false, isWard: false, isCritical: false, hasCustomOverride: false };
            this.masterSearch = '';
        },

        toggleAllRows(event, context = 'queue') {
            if (context === 'queue') this.selectedRows = event.target.checked ? this.processedQueue.map(app => app.ticket) : [];
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

                if (!this.selectedApplicant) {
                    this.selectedApplicant = this.archivedApplications.find(a => a.ticket === ticketId);
                    isArchived = true;
                }

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