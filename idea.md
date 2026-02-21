I want main progress to be a live claude code with tmux that controls everything.

It should receive an initial instruction about a research goal, and call two python functions A and B.

Then there are 3 steps:

1. A takes input of a research topic, such as "nnunet improvements", and output is most related literature not found.
2. B reads the paper from A and merge it into the existing codebase. Gitlab is used to tract the code change.
3. The main progress summarizes the effect of the new code implemented by B and present it to the user. 

Optionally, user will provide some feedbacks, and the main progress should restart from 1. 
Different from the 1st time, now step 1 should find new paper based on the summary of step 3 and user inputs.
If user inputs is unrelated to find new ideas, go to step 2 directly
