"""The portal's outbound email.

    views.py  ->  queue_notification()  ->  a row in `notifications`
                                                    |
                        manage.py send_notifications |
                                                    v
                                          Sent, or Failed with a reason

Nothing in views.py sends an email. Views queue; a cron job sends. That split is
what makes a delivery failure survivable: the HR action completes and is
recorded whatever the mail relay is doing, and a message that could not be
delivered leaves a row saying so rather than a 500 in somebody's browser.

  types.py       the nine types, and the template file each one uses
  recipients.py  who receives what -- the one place that rule exists
  content.py     filling HR's templates; HR's words are in templates/, not here
  queue.py       queue_notification(), the function views.py calls
"""
