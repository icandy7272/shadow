# Responsive desktop workspace

User approved direct implementation, retaining mobile experience and making use of desktop width. Preserve all recording, navigation, shortcuts and authentication behavior.

- A dedicated desktop stylesheet at >=1100px provides a 216px side navigation and content up to1280px; mobile/tablet retain existing single-column/bottom-navigation rules. Login/account/settings retain readable form widths.
- Semantic wrappers make today a primary practice column plus daily plan, records overview/calendar plus fullwidth history, library a responsive cardgrid, and start categories two columns. Source catalogue stays a desktop table; vocabulary gets wider aligned rows without a new detail-interaction contract.
- Practice retains the single active learning step and never reveals text prematurely. Desktop adds a session information rail containing existing context/progress/step navigation; main learning/result column and diagrams widen. Action dock aligns to the working region rather than fullwindow. Side navigation remains protected during recording. Avoid cloning active recorder controls.
- Desktop CSS responds to root text scale (rem breakpoints) and retains keyboard focus/order, loading/error/modal states. Validate1440/1280/1100 plus tablet/mobile390/320 and200%text; test blank/data-rich and saved/recording scenarios.
- Automated testregressions, independentreview, browser screenshots and alltests precede commit/push; no private data inGit.
