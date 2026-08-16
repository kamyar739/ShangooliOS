"""Curated, offline candidate generation for profession mug collections."""


DOCTOR_IDEAS = (
    ("Doctor Humor", "I Read Charts So You Don't Have To."),
    ("Doctor Humor", "Powered by Rounds and Coffee."),
    ("Doctor Humor", "I Have a Differential for That."),
    ("Doctor Humor", "My Schedule Has a Schedule."),
    ("Doctor Humor", "Today Was Medically Interesting."),
    ("Doctor Humor", "I Speak Fluent Lab Results."),
    ("Doctor Humor", "Please Hold. I'm Thinking Medically."),
    ("Doctor Humor", "I Came. I Saw. I Ordered Labs."),
    ("Doctor Humor", "Professional Opinion Loading…"),
    ("Doctor Humor", "This Is My Clinical Face."),
    ("Patient Logic", "The Internet Said It Was Rare."),
    ("Patient Logic", "I Respect the Confidence in Your Self-Diagnosis."),
    ("Patient Logic", "You Saved the Important Symptom for Last."),
    ("Patient Logic", "Yes, That Medication Still Counts."),
    ("Patient Logic", "Your Search History Has Joined the Consult."),
    ("Patient Logic", "When Did It Start? Apparently, That's Classified."),
    ("Patient Logic", "A Very Specific Maybe Is Still a Maybe."),
    ("Patient Logic", "The Allergy List Has Entered the Chat."),
    ("Patient Logic", "No, 'The Little White Pill' Is Not a Medication Name."),
    ("Patient Logic", "Let's Revisit the Part You Forgot to Mention."),
    ("On Call Humor", "On Call: Because Sleep Was Getting Repetitive."),
    ("On Call Humor", "My Pager Has Excellent Timing and Terrible Manners."),
    ("On Call Humor", "Available, Awake, and Questioning My Choices."),
    ("On Call Humor", "I Survived the Night Shift. Allegedly."),
    ("On Call Humor", "Call Room: Where Five Minutes Counts as Sleep."),
    ("On Call Humor", "Good Morning Is a Bold Assumption."),
    ("On Call Humor", "The Sun Is Up. This Feels Personal."),
    ("On Call Humor", "My Circadian Rhythm Has Left the Building."),
    ("On Call Humor", "Rested Is Not One of Today's Findings."),
    ("On Call Humor", "I Put the 'Why' in 3 A.M."),
    ("Chart Humor", "The Chart Remembers What I Don't."),
    ("Chart Humor", "If It Isn't Documented, Did It Even Happen?"),
    ("Chart Humor", "My Love Language Is a Completed Note."),
    ("Chart Humor", "One More Note and Then I Become a Person Again."),
    ("Chart Humor", "This Meeting Could Have Been a Chart Note."),
    ("Chart Humor", "I Came for the Medicine. I Stayed for the Documentation."),
    ("Chart Humor", "Autocorrect Is Not Board Certified."),
    ("Chart Humor", "Signed, Sealed, Electronically Filed."),
    ("Chart Humor", "The Note Is Done. Please Hold Your Applause."),
    ("Chart Humor", "Charting: The Sequel Nobody Requested."),
    ("Medical Wordplay", "I Have Patients. Just Not Patience."),
    ("Medical Wordplay", "Keep Calm and Check the Vitals."),
    ("Medical Wordplay", "Diagnosis Before Decaf Is an Advanced Skill."),
    ("Medical Wordplay", "I Find Your Lack of Evidence Disturbing."),
    ("Medical Wordplay", "My Favorite Organ Is the One Behaving Today."),
    ("Medical Wordplay", "Let's Not Make This a Case Report."),
    ("Medical Wordplay", "That Escalated Clinically."),
    ("Medical Wordplay", "Normal Is Just a Reference Range."),
    ("Medical Wordplay", "I Make Very Educated Guesses."),
    ("Medical Wordplay", "Trust the Process. Verify the Dosage."),
)


WITTY_DOCTOR_IDEAS = (
    ("Double-Take Wit", "My Poker Face Is HIPAA Compliant."),
    ("Double-Take Wit", "The Good News: I Have a Plan. The Plan Has Questions."),
    ("Double-Take Wit", "My Differential Has a Differential."),
    ("Double-Take Wit", "I Have a Medical Degree and Still Can't Fix the Printer."),
    ("Double-Take Wit", "Your Secret Is Safe With Me. It's in the Chart."),
    ("Double-Take Wit", "I Don't Jump to Conclusions. I Order Tests First."),
    ("Double-Take Wit", "Clinically Speaking, That's a Lot."),
    ("Double-Take Wit", "Second Opinions Welcome. Second Inboxes, No."),
    ("Double-Take Wit", "I Treat Symptoms. The Wi-Fi Is Beyond My Scope."),
    ("Double-Take Wit", "Please Don't Confuse My Calm With Available."),
    ("Double-Take Wit", "The Results Are In. They Would Like More Results."),
    ("Double-Take Wit", "I Have Follow-Up Questions About Your Follow-Up Questions."),
    ("Double-Take Wit", "The Chart Says Stable. The Schedule Disagrees."),
    ("Double-Take Wit", "Everything Is Under Control. None of It Is Mine."),
    ("Double-Take Wit", "This Is Not My First Differential. It May Be My Longest."),
    ("Double-Take Wit", "My Bedside Manner Has Office Hours."),
    ("Double-Take Wit", "The Diagnosis Was Easier Than the Password Reset."),
    ("Double-Take Wit", "I Believe in Work-Life Balance. I Have Read About It."),
    ("Double-Take Wit", "I Asked the Chart. The Chart Asked for an Update."),
    ("Double-Take Wit", "The Patient Is Resting. The Inbox Is Not."),
    ("Double-Take Wit", "I Have Great Patients. Patience Is Still Pending."),
    ("Double-Take Wit", "That Sounds Rare. So Does a Lunch Break."),
    ("Double-Take Wit", "My Clinical Judgment Is Fine. My Calendar Needs a Consult."),
    ("Double-Take Wit", "The Human Body Is Amazing. Scheduling Is Not."),
    ("Double-Take Wit", "I Can Cure Many Things. Monday Is Not One of Them."),
    ("Double-Take Wit", "Today's Prognosis: Meetings."),
    ("Double-Take Wit", "I Keep an Open Mind and a Closed Chart."),
    ("Double-Take Wit", "The Note Is Brief. The Day Was Not."),
    ("Double-Take Wit", "No Pressure. Just Vitals."),
    ("Double-Take Wit", "I Listen to My Patients. My Pager Interrupts."),
    ("Double-Take Wit", "The Evidence Is Compelling. The Printer Is Not."),
    ("Double-Take Wit", "I Have Seen the Future. It Needs Prior Authorization."),
    ("Double-Take Wit", "The Plan Is Clear. The Handwriting Remains a Mystery."),
    ("Double-Take Wit", "My Notes Have Notes."),
    ("Double-Take Wit", "I Ordered Patience. It's Backordered."),
    ("Double-Take Wit", "The Waiting Room Has Trust Issues."),
    ("Double-Take Wit", "My Specialty Is Being Needed During Lunch."),
    ("Double-Take Wit", "The Symptoms Are Improving. The Paperwork Is Chronic."),
    ("Double-Take Wit", "Medicine Is Full of Answers. Most Begin With 'It Depends.'"),
    ("Double-Take Wit", "I Found the Problem. It Has a Meeting Invite."),
    ("Double-Take Wit", "The Scan Was Clear. My Afternoon Was Not."),
    ("Double-Take Wit", "I Practice Preventive Medicine. Mostly Preventing Lunch."),
    ("Double-Take Wit", "The Consult Was Brief, in the Geological Sense."),
    ("Double-Take Wit", "I Have Boundaries. They Are Currently on Call."),
    ("Double-Take Wit", "My Professional Opinion Has Been Professionally Delayed."),
    ("Double-Take Wit", "The Case Is Closed. The Tabs Are Not."),
    ("Double-Take Wit", "I Make Life-or-Death Decisions. Then I Choose a Lunch."),
    ("Double-Take Wit", "The Body Keeps the Score. The EHR Keeps Everything Else."),
    ("Double-Take Wit", "I Was Promised a Practice. This Feels Very Real."),
    ("Double-Take Wit", "My Calm Is Evidence-Based."),
)


_DOCTOR_HUMOR_PATTERNS = (
    ("Doctor Humor", "My {} and I Are in a Complicated Relationship.", ("Pager", "Inbox", "Schedule", "Stethoscope", "Dictation Software")),
    ("Doctor Humor", "{}: A Bold Choice Before Rounds.", ("Optimism", "Decaf", "Skipping Breakfast", "A Quiet Hallway", "An Empty Inbox")),
    ("Doctor Humor", "I Was Told There Would Be {}.", ("Coffee", "Fewer Meetings", "A Lunch Break", "Legible Handwriting", "Normal Lab Results")),
    ("Doctor Humor", "Plot Twist: {}.", ("The Patient Remembered the Medication", "The Note Saved", "The Consult Called Back", "The Scan Was Normal", "Lunch Actually Happened")),
    ("Doctor Humor", "{} Is Doing a Lot of Work in That Sentence.", ("Stable", "Brief", "Routine", "Uncomplicated", "Asymptomatic")),
    ("Doctor Humor", "Ask Me Again After {}.", ("Rounds", "Coffee", "I Read the Chart", "The Lab Results", "My Second Coffee")),
    ("On Call Humor", "{} Has Excellent Timing and Terrible Manners.", ("The Overnight Page", "The Call Phone", "That Alarm", "The Emergency Consult", "The 3 A.M. Question")),
    ("On Call Humor", "Currently Running on {}.", ("Caffeine and Clinical Judgment", "Four Minutes of Sleep", "Snacks and Determination", "Pager Anxiety", "Pure Professionalism")),
    ("On Call Humor", "{} Counts as Sleep on Call.", ("Closing My Eyes", "Sitting Down", "A Quiet Elevator Ride", "Five Uninterrupted Minutes", "Blinking Slowly")),
    ("On Call Humor", "Night Shift: Where {}.", ("Breakfast Is a State of Mind", "Tuesday Becomes Wednesday", "Coffee Becomes a Food Group", "Time Loses All Meaning", "The Vending Machine Knows Your Name")),
    ("On Call Humor", "I Came in for One Shift and Left in {}.", ("Another Time Zone", "A Different Season", "A New Tax Year", "Tomorrow", "Need of a Nap")),
    ("On Call Humor", "Do Not Disturb Unless {}.", ("It Is Actually Disturbing", "The Labs Are Back", "Coffee Has Arrived", "The Pager Is on Fire", "You Brought Snacks")),
    ("Chart Humor", "My {} Deserves Its Own Billing Code.", ("Inbox", "To-Do List", "Charting Backlog", "Unread Message Count", "Documentation Fatigue")),
    ("Chart Humor", "The Note Was Almost Done. Then {}.", ("The Computer Updated", "The Wi-Fi Blinked", "Someone Said Addendum", "The Phone Rang", "Autocorrect Got Creative")),
    ("Chart Humor", "{}: Because the First Note Wasn't Long Enough.", ("Addendum", "Correction", "Clarification", "Late Entry", "Second Addendum")),
    ("Chart Humor", "I Practice Evidence-Based {}.", ("Charting", "Inbox Avoidance", "Copy Editing", "Tab Management", "Keyboard Staring")),
    ("Chart Humor", "Today's Workout: {}.", ("Closing Browser Tabs", "Chasing Lab Results", "Refreshing the Inbox", "Lifting the Chart", "Running Behind")),
    ("Chart Humor", "Everything Is Fine Except {}.", ("The Inbox", "The Schedule", "The Printer", "The Password Reset", "All the Red Alerts")),
    ("Patient Logic", "The Patient Said {}.", ("It's Probably Nothing", "I Only Googled It Once", "I Forgot My Medication List", "It Started a While Ago", "The Pain Is a Twelve")),
    ("Patient Logic", "Medical History: {}.", ("It's Complicated", "See Attached Novel", "Patient Will Explain Eventually", "Updated During the Visit", "Subject to Change")),
    ("Patient Logic", "Chief Complaint: {}.", ("Everything Since Tuesday", "A Very Long Story", "Google Was Unhelpful", "My Family Made Me Come", "This Weird Thing")),
    ("Patient Logic", "Apparently, {} Was Important.", ("The Fever", "The Allergy", "The Second Medication", "The Recent Surgery", "The Part About Fainting")),
    ("Patient Logic", "I Asked One Question and Got {}.", ("The Director's Cut", "Three Generations of History", "A Surprise Plot Twist", "A Ten-Minute Prologue", "An Entire Prequel")),
    ("Patient Logic", "Nothing Changed Except {}.", ("All the Symptoms", "The Medication", "The Pain", "The Timeline", "Everything Relevant")),
    ("Medical Wordplay", "Keep Your Friends Close and Your {} Closer.", ("Lab Results", "Coffee", "Stethoscope", "Differential", "Medication List")),
    ("Medical Wordplay", "I Put the Pro in {}.", ("Prognosis", "Progress Notes", "Procrastinating Lunch", "Professional Concern", "Problem Lists")),
    ("Medical Wordplay", "Living the {} Dream.", ("Clinical", "Differential", "Documentation", "Night-Shift", "Prior-Authorization")),
    ("Medical Wordplay", "A Little {} Never Hurt Anybody. Probably.", ("Clinical Suspicion", "Diagnostic Curiosity", "Medical Caution", "Differential Thinking", "Follow-Up")),
    ("Medical Wordplay", "My Superpower Is {}.", ("Finding the Missing Lab", "Reading Tiny Print", "Remembering Drug Interactions", "Staying Calm in Hallways", "Turning Coffee into Notes")),
    ("Medical Wordplay", "I Like My {} Like I Like My Coffee.", ("Notes Complete", "Plans Clear", "Labs Reviewed", "Handoffs Strong", "Differentials Broad")),
)


def _doctor_idea_bank():
    ideas = [*DOCTOR_IDEAS, *WITTY_DOCTOR_IDEAS]
    for category, template, options in _DOCTOR_HUMOR_PATTERNS:
        ideas.extend((category, template.format(option)) for option in options)
    return ideas


def generated_profession_ideas(profession, count=50, excluded_texts=()):
    """Return an original curated pool without network calls or publishing."""
    normalized = " ".join((profession or "").split()).casefold()
    if normalized != "doctor":
        raise ValueError(
            "Automatic candidates are currently prepared for Doctor Mugs only"
        )
    normalized_count = int(count)
    if normalized_count < 1:
        raise ValueError("Choose at least one idea")
    excluded = {" ".join((text or "").casefold().split()) for text in excluded_texts}
    available = [
        idea for idea in _doctor_idea_bank()
        if " ".join(idea[1].casefold().split()) not in excluded
    ]
    if not available:
        raise ValueError("Every prepared doctor joke is already in your idea list")
    return available[:normalized_count]
