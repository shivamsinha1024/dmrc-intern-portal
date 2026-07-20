/**
 * DMRC INTERN REFERRAL WIZARD — RELEASABLE APPS ENGINE
 * Powered natively by Alpine.js reactive state architecture.
 */
document.addEventListener('alpine:init', () => {
    Alpine.data('wizardEngine', () => ({
        // Interface View Layout State
        portalState: 'dashboard', 
        activeTab: 'submitted',
        showValidationWarning: false,
        searchQuery: '',

        // Navigation Controllers
        currentStep: 1,
        highestStepReached: 1,
        totalSteps: 5,
        
        // Identity & Synchronization Stamps
        applicationCode: 'DRAFT · NOT ISSUED',
        saveStatus: 'Not saved yet',

        // Final Submission State
        acceptedDeclarations: false,   
        showSubmitConfirm: false,      
        finalTicket: null,             
        submittedAt: '',
        reviewSections: { 1: true, 2: false, 3: false, 4: false },

        // CORRECTION LOOP STATE
        isCorrectionMode: false, 
        correctionRemarks: '',

        unloadGuard: null,

        // SESSION MOCK
        sessionEmployee: {
            empId: 'EMP-4471',
            name: 'R. Sharma',
            designation: 'Senior Engineer',
            department: 'Signal & Telecom'
        },

        // Global Application State Matrix (Active Form)
        student: { fullName: '', fathersName: '', gender: '', dateOfBirth: '', mobile_number: '', personal_email: '', permanent_address: '', emergency_contact_name: '', emergency_contact_mobile: '' },
        academic: { university_name: '', college_name: '', course: '', course_other: '', branch: '', branch_other: '', current_semester: '', grading_system: 'CGPA', current_score: '' },
        documents: { aadhar: null, college_id: null, lor: null, photograph: null, signature: null },
        aadhaarConsent: false,
        placement: { cycle_id: null, sessionTerm: '', department_id: '', duration_weeks: '', requested_doj: '', is_ward: false },

        // --- DATA LISTS ---
        courseOptions: ['B.Tech / B.E.', 'M.Tech / M.E.', 'BCA', 'MCA', 'B.Sc', 'M.Sc', 'BBA', 'MBA / PGDM', 'B.Com', 'M.Com', 'LLB', 'LLM', 'BA / MA', 'Diploma'],
        branchOptions: ['Computer Science & Engineering', 'Information Technology', 'Electronics & Communication', 'Electrical Engineering', 'Mechanical Engineering', 'Civil Engineering', 'Finance', 'Marketing', 'Human Resources', 'Operations', 'Accounting', 'Commerce', 'Corporate Law', 'General Law', 'Physics', 'Chemistry', 'Mathematics', 'General'],
        documentLabels: { aadhar: 'AADHAR', college_id: 'College ID', lor: 'Letter of Recommendation', photograph: 'Passport Size Photograph', signature: 'Signature' },
        stepTitles: { 1: 'Student Details', 2: 'Academic Matrix', 3: 'Document Vault', 4: 'Internship Details' },
        dmrcDepartments: ['Civil', 'Mechanical/RS', 'Electrical', 'IT', 'S&T', 'Finance', 'HR', 'Legal'],

        // --- DYNAMIC DB MOCKS ---
        dbJoiningDates: [
            { cycle_id: 1, date: '2026-05-04' }, { cycle_id: 1, date: '2026-05-11' }, { cycle_id: 1, date: '2026-05-18' }, { cycle_id: 1, date: '2026-05-25' }, { cycle_id: 1, date: '2026-06-08' }, { cycle_id: 1, date: '2026-06-22' },
            { cycle_id: 2, date: '2026-12-07' }, { cycle_id: 2, date: '2026-12-14' }, { cycle_id: 2, date: '2026-12-21' }, { cycle_id: 2, date: '2026-12-28' }, { cycle_id: 2, date: '2027-01-11' }, { cycle_id: 2, date: '2027-01-25' }
        ],

        // Cycle Capacity Snapshots (Dynamic Real-Time Counter Objects)
        summerCapacity: { 'Civil': { max: 25, occ: 15 }, 'Mechanical/RS': { max: 25, occ: 10 }, 'Electrical': { max: 40, occ: 20 }, 'IT': { max: 25, occ: 25 }, 'S&T': { max: 40, occ: 30 }, 'Finance': { max: 10, occ: 5 }, 'HR': { max: 5, occ: 5 }, 'Legal': { max: 5, occ: 2 } },
        winterCapacity: { 'Civil': { max: 25, occ: 10 }, 'Mechanical/RS': { max: 25, occ: 5 }, 'Electrical': { max: 40, occ: 15 }, 'IT': { max: 25, occ: 28 }, /* Triggers Negative Waitlist */ 'S&T': { max: 40, occ: 20 }, 'Finance': { max: 10, occ: 2 }, 'HR': { max: 5, occ: 1 }, 'Legal': { max: 5, occ: 0 } },

        get currentCycleCapacity() {
            if (this.placement.cycle_id === 1) return this.summerCapacity;
            if (this.placement.cycle_id === 2) return this.winterCapacity;
            return null;
        },
        get selectedDeptCapacity() {
            const caps = this.currentCycleCapacity;
            if (caps && this.placement.department_id) return caps[this.placement.department_id];
            return null;
        },
        get isWaitlisted() {
            const cap = this.selectedDeptCapacity;
            if (!cap) return false;
            return (cap.max - cap.occ) <= 0;
        },

        // ==========================================
        // MOCK DASHBOARD DATABASE (PRESENTATION DATA)
        // ==========================================
        selectedDrawerApp: null,

        baseProfile: {
            student: { fullName: 'Shivam Sinha', fathersName: 'Sunil Kumar', gender: 'Male', dateOfBirth: '29-12-2004', mobile_number: '7007709797', personal_email: 'shivamsinha1024@gmail.com', permanent_address: '6/130, Subhash Nagar, West Delhi, New Delhi. 110027', emergency_contact_name: 'Sunil Kumar', emergency_contact_mobile: '9792120077' },
            academic: { university_name: 'Guru Gobind Singh Indraprastha University', college_name: 'Guru Tegh Bahadur Institute of Technology', course: 'B.Tech / B.E.', course_other: '', branch: 'Information Technology', branch_other: '', current_semester: '4', grading_system: 'CGPA', current_score: '8.8' },
            documents: { aadhar: { name: 'Shivam.pdf' }, college_id: { name: 'Student ID Front.jpeg' }, lor: { name: 'TnP Letter.pdf' }, photograph: { name: 'Shivam Photograph.jpg' }, signature: { name: 'Shivam Signature.jpg' } }
        },

        mockApplications: [],

        init() {
            const bp = this.baseProfile;
            
            this.mockApplications = [
                // --- SUBMITTED TAB (10 Applications Sorted Globally) ---
                { id: 1, tab: 'submitted', status: 'Under Verification', badge: 'bg-warning text-dark', ticketId: 'DMRC-2026W-101', targetCycle: 'Winter 2026', createdDate: '15-07-2026', dept: 'IT', duration: '4 Weeks', doj: '2026-12-14', isWard: false,
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [ { date: '15-07-2026', title: 'Application Submitted', desc: 'Locked and sent to HR queue.' } ] },
                  
                { id: 2, tab: 'submitted', status: 'Approved', badge: 'bg-primary', ticketId: 'DMRC-2026S-102', targetCycle: 'Summer 2026', createdDate: '10-04-2026', dept: 'Finance', duration: '6 Weeks', doj: '2026-05-11', isWard: false,
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [ { date: '10-04-2026', title: 'Application Submitted' }, { date: '18-04-2026', title: 'Approved', desc: 'Awaiting formal schedule.' } ] },

                { id: 3, tab: 'submitted', status: 'Scheduled', badge: 'bg-info text-dark', ticketId: 'DMRC-2026S-103', targetCycle: 'Summer 2026', createdDate: '02-04-2026', dept: 'HR', duration: '4 Weeks', doj: '2026-05-04', isWard: false,
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [ { date: '02-04-2026', title: 'Application Submitted' }, { date: '08-04-2026', title: 'Approved' }, { date: '15-04-2026', title: 'Scheduled', desc: 'Joining letter issued.' } ] },

                { id: 4, tab: 'submitted', status: 'Active Intern', dbStatus: 'Joined', badge: 'bg-success', ticketId: 'DMRC-2026S-104', targetCycle: 'Summer 2026', createdDate: '01-04-2026', dept: 'IT', duration: '8 Weeks', doj: '2026-05-04', isWard: true,
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [ { date: '01-04-2026', title: 'Application Submitted' }, { date: '08-04-2026', title: 'Approved' }, { date: '10-04-2026', title: 'Scheduled' }, { date: '04-05-2026', title: 'Joined (Active Intern)', desc: 'Candidate reported successfully.' } ] },

                { id: 5, tab: 'submitted', status: 'Completed', badge: 'bg-secondary', ticketId: 'DMRC-2025W-105', targetCycle: 'Winter 2025', createdDate: '15-11-2025', dept: 'Civil', duration: '4 Weeks', doj: '2025-12-08', isWard: false,
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [ { date: '15-11-2025', title: 'Application Submitted' }, { date: '18-11-2025', title: 'Approved' }, { date: '25-11-2025', title: 'Scheduled' }, { date: '08-12-2025', title: 'Joined' }, { date: '10-01-2026', title: 'Completed', desc: 'Internship concluded. Certificate issued.' } ] },

                { id: 6, tab: 'submitted', status: 'Rejected', badge: 'bg-danger', ticketId: 'DMRC-2025S-107', targetCycle: 'Summer 2025', createdDate: '10-03-2025', dept: 'Legal', duration: '4 Weeks', doj: '2025-05-05', isWard: false, remarks: 'Invalid Document: Correction Lifeline Exhausted.',
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [ { date: '10-03-2025', title: 'Application Submitted' }, { date: '12-03-2025', title: 'Re-Opened (Correction)' }, { date: '15-03-2025', title: 'Resubmitted' }, { date: '23-03-2025', title: 'Rejected', desc: 'Invalid Document: Correction Lifeline Exhausted.' } ] },

                { id: 7, tab: 'submitted', status: 'Rejected', badge: 'bg-danger', ticketId: 'DMRC-2025S-108', targetCycle: 'Summer 2025', createdDate: '01-03-2025', dept: 'S&T', duration: '6 Weeks', doj: '2025-05-12', isWard: false, remarks: 'No-Show: Life Exhausted.',
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [ { date: '01-03-2025', title: 'Application Submitted' }, { date: '10-03-2025', title: 'Approved' }, { date: '15-03-2025', title: 'Scheduled' }, { date: '13-05-2025', title: 'Re-Opened (No-Show)' }, { date: '14-05-2025', title: 'Resubmitted' }, { date: '18-05-2025', title: 'Approved' }, { date: '20-05-2025', title: 'Scheduled' }, { date: '30-05-2025', title: 'Rejected', desc: 'No-Show: Life Exhausted.' } ] },

                { id: 8, tab: 'submitted', status: 'Rejected', badge: 'bg-danger', ticketId: 'DMRC-2025S-109', targetCycle: 'Summer 2025', createdDate: '01-01-2025', dept: 'Electrical', duration: '4 Weeks', doj: '2025-05-19', isWard: false, remarks: 'Lifelines Exhausted: Both Correction and No-Show used.',
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [ { date: '01-01-2025', title: 'Application Submitted' }, { date: '05-01-2025', title: 'Re-Opened (Correction)' }, { date: '06-01-2025', title: 'Resubmitted' }, { date: '10-01-2025', title: 'Approved' }, { date: '12-01-2025', title: 'Scheduled' }, { date: '20-05-2025', title: 'Re-Opened (No-Show)' }, { date: '21-05-2025', title: 'Resubmitted' }, { date: '25-05-2025', title: 'Approved' }, { date: '28-05-2025', title: 'Scheduled' }, { date: '01-06-2025', title: 'Rejected', desc: 'Lifelines Exhausted: Both Correction and No-Show used.' } ] },

                // UPDATED: Now featuring the permanent WL origin stamp
                { id: 9, tab: 'submitted', status: 'Under Verification', badge: 'bg-warning text-dark', ticketId: 'DMRC-2026W-WL-110', targetCycle: 'Winter 2026', createdDate: '18-07-2026', dept: 'Civil', duration: '4 Weeks', doj: '2026-12-21', isWard: false,
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [ { date: '18-07-2026', title: 'Application Submitted' }, { date: '19-07-2026', title: 'Re-Opened (Correction)' }, { date: '20-07-2026', title: 'Resubmitted', desc: 'Awaiting HR Verification.' } ] },

                // --- RE-OPENED TAB (2 Applications) ---
                { id: 10, tab: 'reopened', status: 'Action Required', badge: 'bg-danger', ticketId: 'DMRC-2026W-201', targetCycle: 'Winter 2026', createdDate: '12-07-2026', dept: 'S&T', duration: '6 Weeks', doj: '2026-12-07', isWard: false, remarks: 'Invalid Document: Blurred Aadhaar Card. Please upload a clear PDF.', cycle_id: 2,
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [] },

                { id: 11, tab: 'reopened', status: 'Action Required', badge: 'bg-danger', ticketId: 'DMRC-2026W-202', targetCycle: 'Winter 2026', createdDate: '10-07-2026', dept: 'Civil', duration: '4 Weeks', doj: '2026-12-14', isWard: true, remarks: 'No-Show: Candidate failed to report. Select a new DOJ.', cycle_id: 2,
                  student: bp.student, academic: bp.academic, documents: bp.documents, timeline: [] },

                // --- SAVED TAB (1 Genuinely Incomplete Application) ---
                { id: 12, tab: 'saved', status: 'Draft', badge: 'bg-secondary bg-opacity-25 text-dark border', ticketId: 'DRAFT', targetCycle: 'Winter 2026', createdDate: '19-07-2026', dept: '—', duration: '', doj: '', isWard: false, cycle_id: 2, sessionTerm: 'Winter',
                  student: { fullName: 'Shivam Sinha', fathersName: '', gender: '', dateOfBirth: '', mobile_number: '7007709797', personal_email: 'shivamsinha1024@gmail.com', permanent_address: '', emergency_contact_name: '', emergency_contact_mobile: '' }, 
                  academic: { university_name: '', college_name: '', course: '', course_other: '', branch: '', branch_other: '', current_semester: '', grading_system: 'CGPA', current_score: '' }, 
                  documents: { aadhar: null, college_id: null, lor: null, photograph: null, signature: null }, timeline: [] }
            ];
        },

        // Search & Sorting Compute Node (Sorted by submission date automatically)
        get sortedAndFilteredApps() {
            let filtered = this.mockApplications.filter(app => {
                if (!this.searchQuery) return true;
                const query = this.searchQuery.toLowerCase();
                const nameMatch = app.student.fullName.toLowerCase().includes(query);
                const ticketMatch = app.ticketId.toLowerCase().includes(query);
                return nameMatch || ticketMatch;
            });

            return filtered.sort((a, b) => {
                const dateA = a.createdDate.split('-').reverse().join('-');
                const dateB = b.createdDate.split('-').reverse().join('-');
                return dateB.localeCompare(dateA); 
            });
        },

        get savedApps() { return this.sortedAndFilteredApps.filter(a => a.tab === 'saved'); },
        get submittedApps() { return this.sortedAndFilteredApps.filter(a => a.tab === 'submitted'); },
        get reopenedApps() { return this.sortedAndFilteredApps.filter(a => a.tab === 'reopened'); },

        // DASHBOARD ACTIONS
        viewTicket(app) {
            this.selectedDrawerApp = app;
            const offcanvasElement = document.getElementById('ticketDrawer');
            const offcanvas = new bootstrap.Offcanvas(offcanvasElement);
            offcanvas.show();
        },

        startNewApplication() {
            this.resetFormState();
            this.portalState = 'cycle_select';
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        returnToDashboard() {
            if (this.unloadGuard) { window.removeEventListener('beforeunload', this.unloadGuard); this.unloadGuard = null; }
            this.resetFormState();
            this.portalState = 'dashboard';
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        resumeDraft(app) {
            this.resetFormState();
            this.placement.cycle_id = app.cycle_id;
            this.placement.sessionTerm = app.sessionTerm;
            this.applicationCode = `DMRC-2026W-PENDING`;
            this.loadMockDataIntoForm(app);
            this.isCorrectionMode = false;
            this.highestStepReached = 1; 
            this.currentStep = 1;
            this.initializeWizard();
        },

        fixApplication(app) {
            this.resetFormState();
            this.placement.cycle_id = app.cycle_id;
            this.placement.sessionTerm = app.targetCycle.split(' ')[0];
            this.applicationCode = app.ticketId;
            this.loadMockDataIntoForm(app);
            this.isCorrectionMode = true;
            this.correctionRemarks = app.remarks;
            this.highestStepReached = 5;
            this.currentStep = 1;
            this.initializeWizard();
        },

        loadMockDataIntoForm(app) {
            this.student = JSON.parse(JSON.stringify(app.student));
            this.academic = JSON.parse(JSON.stringify(app.academic));
            this.placement.department_id = app.dept !== '—' ? app.dept : '';
            this.placement.duration_weeks = app.duration ? app.duration.charAt(0) : '';
            this.placement.requested_doj = app.doj;
            this.placement.is_ward = app.isWard;
            
            for(let key in app.documents) {
                if(app.documents[key]) {
                    this.documents[key] = { name: app.documents[key].name, previewUrl: `./Dummy Docs/${app.documents[key].name}` };
                }
            }
            if(this.documents.aadhar) this.aadhaarConsent = true;
        },

        resetFormState() {
            this.student = { fullName: '', fathersName: '', gender: '', dateOfBirth: '', mobile_number: '', personal_email: '', permanent_address: '', emergency_contact_name: '', emergency_contact_mobile: '' };
            this.academic = { university_name: '', college_name: '', course: '', course_other: '', branch: '', branch_other: '', current_semester: '', grading_system: 'CGPA', current_score: '' };
            this.documents = { aadhar: null, college_id: null, lor: null, photograph: null, signature: null };
            this.placement = { cycle_id: null, sessionTerm: '', department_id: '', duration_weeks: '', requested_doj: '', is_ward: false };
            this.aadhaarConsent = false;
            this.acceptedDeclarations = false;
            this.isCorrectionMode = false;
            this.correctionRemarks = '';
            this.currentStep = 1;
            this.highestStepReached = 1;
        },

        initDOJCalendar(element) {
            const allowedDates = this.dbJoiningDates.filter(d => d.cycle_id === this.placement.cycle_id).map(d => d.date);
            flatpickr(element, { dateFormat: 'Y-m-d', altInput: true, altFormat: 'd-m-Y', enable: allowedDates, minDate: "today" });
        },

        // --- INPUT MASKING & VALIDATIONS ---
        restrictMobileInput(fieldPath, nextFieldId) {
            let clean = this.student[fieldPath].replace(/\D/g, '');
            if (clean.length > 10) clean = clean.substring(0, 10);
            this.student[fieldPath] = clean;
            if (clean.length === 10 && nextFieldId) {
                this.$nextTick(() => { const nextEl = document.getElementById(nextFieldId); if (nextEl) nextEl.focus(); });
            }
        },
        isMobileInvalid(fieldPath) {
            const val = this.student[fieldPath]; return val.length > 0 && val.length < 10;
        },
        isEmailInvalid() {
            const val = this.student.personal_email; return val.length > 0 && !val.includes('@');
        },
        restrictScoreInput() {
            let val = this.academic.current_score.replace(/[^0-9.]/g, '');
            const parts = val.split('.');
            if (parts.length > 2) val = parts[0] + '.' + parts.slice(1).join('');
            let num = parseFloat(val);
            if (!isNaN(num)) {
                if (this.academic.grading_system === 'CGPA' && num > 10) val = '10';
                if (this.academic.grading_system === 'Percentage' && num > 100) val = '100';
            }
            this.academic.current_score = val;
        },

        // --- FILE HANDLING LOGIC ---
        handleFileUpload(event, docType) {
            const file = event.target.files[0];
            if (!file) {
                this.documents[docType] = null;
                if (docType === 'aadhar') this.aadhaarConsent = false;
                return;
            }
            const maxSize = 5 * 1024 * 1024;
            if (file.size > maxSize) {
                alert(`Upload failed: The file "${file.name}" exceeds the 5MB limit.`);
                event.target.value = ''; this.documents[docType] = null;
                if (docType === 'aadhar') this.aadhaarConsent = false;
                return;
            }
            const validImageTypes = ['image/jpeg', 'image/png'];
            const validDocumentTypes = ['image/jpeg', 'image/png', 'application/pdf'];
            if (docType === 'photograph' || docType === 'signature') {
                if (!validImageTypes.includes(file.type)) {
                    alert("Invalid format: Photograph and Signature must be JPG or PNG.");
                    event.target.value = ''; this.documents[docType] = null; return;
                }
            } else {
                if (!validDocumentTypes.includes(file.type)) {
                    alert("Invalid format: Document must be PDF, JPG, or PNG.");
                    event.target.value = ''; this.documents[docType] = null;
                    if (docType === 'aadhar') this.aadhaarConsent = false; return;
                }
            }
            
            this.documents[docType] = { file: file, name: file.name, previewUrl: URL.createObjectURL(file) };
            if (docType === 'aadhar') this.aadhaarConsent = false; 
            this.saveStatus = new Date().toLocaleTimeString();
        },

        previewDocument(docType) {
            const doc = this.documents[docType];
            if (doc && doc.previewUrl) window.open(doc.previewUrl, '_blank');
        },
        
        previewDrawerDocument(docObj) {
            if(docObj && docObj.name) window.open(`./Dummy Docs/${docObj.name}`, '_blank');
        },

        getUploadedCount() {
            return Object.values(this.documents).filter(doc => doc !== null).length;
        },
        getDrawerUploadedCount() {
            if(!this.selectedDrawerApp) return 0;
            return Object.values(this.selectedDrawerApp.documents).filter(doc => doc !== null).length;
        },

        // --- WORKFLOW CONTROLS ---
        confirmCycleSelection(cycleName, id) {
            this.placement.sessionTerm = cycleName;
            this.placement.cycle_id = id;
            this.applicationCode = `DMRC-2026${cycleName.substring(0,1).toUpperCase()}-PENDING`;
            
            this.$nextTick(() => {
                const tableSection = document.getElementById('capacityTableSection');
                if (tableSection) {
                    tableSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            });
        },

        initializeWizard() {
            if (this.placement.cycle_id) {
                this.portalState = 'form_wizard';
                this.saveStatus = new Date().toLocaleTimeString();
                this.unloadGuard = (e) => { e.preventDefault(); e.returnValue = ''; };
                window.addEventListener('beforeunload', this.unloadGuard);
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        },

        // --- UNIFIED VALIDATION ENGINE ---
        getStepMissing(step) {
            const missing = [];
            const blank = (v) => v === null || v === undefined || String(v).trim() === '';

            if (step === 1) {
                const bio = [['fullName', 'Full Name'],['fathersName', "Father's Name"],['gender', 'Gender'],['dateOfBirth', 'Date of Birth'],['mobile_number', 'Mobile Number'],['personal_email', 'Email ID'],['permanent_address', 'Permanent Address'],['emergency_contact_name', 'Emergency Contact Name'],['emergency_contact_mobile', 'Emergency Contact Mobile']];
                for (const [field, label] of bio) { if (blank(this.student[field])) missing.push(label); }
                if (this.student.mobile_number.length > 0 && this.student.mobile_number.length !== 10) missing.push('Mobile Number (must be 10 digits)');
                if (this.student.emergency_contact_mobile.length > 0 && this.student.emergency_contact_mobile.length !== 10) missing.push('Emergency Contact Mobile (must be 10 digits)');
                if (this.student.personal_email.length > 0 && !this.student.personal_email.includes('@')) missing.push('Valid Email ID (missing @ symbol)');
            }
            else if (step === 2) {
                const acad = [['university_name', 'University Name'],['college_name', 'College / Institute Name'],['course', 'Course (Degree)'],['branch', 'Branch / Specialization'],['current_semester', 'Current Semester'],['current_score', 'Current Score']];
                for (const [field, label] of acad) { if (blank(this.academic[field])) missing.push(label); }
                if (this.academic.course === 'Other' && blank(this.academic.course_other)) missing.push('Custom Degree Name');
                if (this.academic.branch === 'Other' && blank(this.academic.branch_other)) missing.push('Custom Branch Name');
            }
            else if (step === 3) {
                for (const [key, label] of Object.entries(this.documentLabels)) { if (!this.documents[key]) missing.push(label); }
                if (this.documents.aadhar && !this.aadhaarConsent) missing.push('Aadhaar Data Consent');
            }
            else if (step === 4) {
                const place = [['department_id', 'Target Department'],['duration_weeks', 'Internship Duration'],['requested_doj', 'Preferred Date of Joining']];
                for (const [field, label] of place) { if (blank(this.placement[field])) missing.push(label); }
            }
            return missing;
        },

        validateCurrentStep() { return this.getStepMissing(this.currentStep).length === 0; },

        get missingByStep() {
            const groups = [];
            for (const step of [1, 2, 3, 4]) {
                const items = this.getStepMissing(step);
                if (items.length > 0) groups.push({ step: step, title: this.stepTitles[step], items: items });
            }
            return groups;
        },
        get isReadyToSubmit() { return this.missingByStep.length === 0; },
        get canSubmit() { return this.isReadyToSubmit && this.acceptedDeclarations; },
        isSectionComplete(step) { return this.getStepMissing(step).length === 0; },
        toggleSection(n) { this.reviewSections[n] = !this.reviewSections[n]; },
        setAllSections(open) { [1, 2, 3, 4].forEach(n => this.reviewSections[n] = open); },
        get allSectionsOpen() { return [1, 2, 3, 4].every(n => this.reviewSections[n]); },

        // --- DISPLAY FORMATTERS ---
        displayValue(v) { return (v === null || v === undefined || String(v).trim() === '') ? '—' : v; },
        displayDate(iso) {
            if (!iso) return '—';
            const parts = iso.split('-');
            if(parts.length === 3 && parts[0].length === 4) return `${parts[2]}-${parts[1]}-${parts[0]}`; 
            return iso; 
        },
        displayCourse(acadObj = this.academic) { return acadObj.course === 'Other' ? acadObj.course_other : acadObj.course; },
        displayBranch(acadObj = this.academic) { return acadObj.branch === 'Other' ? acadObj.branch_other : acadObj.branch; },
        displaySemester(acadObj = this.academic) {
            const s = acadObj.current_semester; if (!s) return '';
            return s === 'Graduated' ? 'Graduated / Alumni' : 'Semester ' + s;
        },
        displayScore(acadObj = this.academic) {
            if (!acadObj.current_score) return '';
            const unit = acadObj.grading_system === 'CGPA' ? ' CGPA (out of 10)' : '% (Percentage)';
            return acadObj.current_score + unit;
        },

        // --- FINAL SUBMISSION FLOW (UPDATED FOR WL- INJECTION) ---
        requestSubmit() { if (this.canSubmit) this.showSubmitConfirm = true; },
        submitApplication() {
            this.showSubmitConfirm = false;
            const seq = String(Math.floor(Math.random() * 900) + 100);
            const cycleLetter = this.placement.sessionTerm.substring(0, 1).toUpperCase();
            
            // Evaluates real-time math and injects the 'WL-' origin stamp if capacity is exceeded
            const wlModifier = this.isWaitlisted ? 'WL-' : '';
            
            this.finalTicket = `DMRC-2026${cycleLetter}-${wlModifier}${seq}`;
            this.applicationCode = this.finalTicket;
            this.submittedAt = new Date().toLocaleString();
            
            if (this.unloadGuard) { window.removeEventListener('beforeunload', this.unloadGuard); this.unloadGuard = null; }
            this.portalState = 'submitted';
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        nextStep() {
            if (this.validateCurrentStep()) this.proceedToNextStep();
            else this.showValidationWarning = true;
        },
        proceedToNextStep() {
            this.showValidationWarning = false;
            if (this.currentStep < this.totalSteps) {
                this.currentStep++;
                if (this.currentStep > this.highestStepReached) this.highestStepReached = this.currentStep;
                this.saveStatus = new Date().toLocaleTimeString();
            }
        },
        prevStep() { if (this.currentStep > 1) this.currentStep--; },
        goToStep(targetStep) { if (targetStep <= this.highestStepReached) this.currentStep = targetStep; }
    }));
});