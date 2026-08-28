# static_attachments

Fixed PDFs that go out with the joining-instructions email. The same files for
every candidate, every time.

This directory is **committed to Git**, deliberately. `media/`,
`generated_documents/`, `protected_documents/` and `signatures/` are all in
`.gitignore`, so anything placed in those would be missing on the deployment
server. These files must travel with the code.

Expected filenames, listed in `STATIC_ATTACHMENTS` at the top of
`portal/management/commands/send_notifications.py`:

    Student_Information_Format.pdf
    List_of_Documents_Required_for_Joining.pdf

If HR's real documents arrive under different names, change them in that one
constant rather than renaming the files.

If a file named here is not present at send time, the notification is recorded
as `Failed` with a reason. It is never sent without its attachments.
