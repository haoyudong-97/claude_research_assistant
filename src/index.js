import { existsSync, mkdirSync, cpSync, rmSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { homedir } from 'os';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SKILL_SRC = join(__dirname, '..', 'skill');

// Claude Code skill directory
const CLAUDE_SKILLS_DIR = join(homedir(), '.claude', 'skills');

const SKILLS = ['idea-iter', 'check-experiments', 'combine-findings'];

function detectClaudeCode() {
  const claudeDir = join(homedir(), '.claude');
  if (existsSync(claudeDir)) {
    return { name: 'Claude Code', path: claudeDir, skillsPath: CLAUDE_SKILLS_DIR };
  }
  return null;
}

function installSkills() {
  const agent = detectClaudeCode();
  if (!agent) {
    console.log('');
    console.log('  Claude Code not detected (~/.claude/ not found).');
    console.log('');
    console.log('  To install manually, copy the skill/ directory to:');
    console.log('    ~/.claude/skills/');
    console.log('');
    process.exit(1);
  }

  console.log(`\n  Found ${agent.name} at ${agent.path}\n`);

  // Ensure skills directory exists
  mkdirSync(agent.skillsPath, { recursive: true });

  // Install each skill
  for (const skill of SKILLS) {
    const src = join(SKILL_SRC, skill);
    const dest = join(agent.skillsPath, skill);

    if (!existsSync(src)) {
      console.log(`  [skip] ${skill} — source not found`);
      continue;
    }

    // Remove existing and copy fresh
    cpSync(src, dest, { recursive: true, force: true });
    console.log(`  [ok]   ${skill} -> ${dest}`);
  }

  // Install shared Python tools into each skill
  const toolsSrc = join(SKILL_SRC, 'research_agent');
  if (existsSync(toolsSrc)) {
    for (const skill of SKILLS) {
      const toolsDest = join(agent.skillsPath, skill, 'research_agent');
      cpSync(toolsSrc, toolsDest, { recursive: true, force: true });
    }
    console.log(`  [ok]   research_agent tools bundled into each skill`);
  }

  console.log('');
  console.log('  Done! Skills installed:');
  console.log('');
  console.log('    /idea-iter <your idea>          — idea -> papers -> code -> launch');
  console.log('    /check-experiments               — collect results from running experiments');
  console.log('    /combine-findings <input>        — integrate a paper/idea into current work');
  console.log('');
  console.log('  Quick start:');
  console.log('    cd /path/to/your/project && claude');
  console.log('    > /idea-iter try attention gates in the decoder');
  console.log('');
}

function uninstallSkills() {
  const agent = detectClaudeCode();
  if (!agent) {
    console.log('  Claude Code not detected. Nothing to uninstall.');
    process.exit(0);
  }

  let removed = 0;
  for (const skill of SKILLS) {
    const dest = join(agent.skillsPath, skill);
    if (existsSync(dest)) {
      rmSync(dest, { recursive: true, force: true });
      console.log(`  [removed] ${skill}`);
      removed++;
    }
  }

  if (removed === 0) {
    console.log('  No idea2code skills found to remove.');
  } else {
    console.log(`\n  Removed ${removed} skill(s).`);
  }
}

function showHelp() {
  console.log(`
  idea2code — autonomous research loop for Claude Code

  Usage:
    npx idea2code              Install skills to Claude Code
    npx idea2code --uninstall  Remove installed skills
    npx idea2code --help       Show this help

  Skills installed:
    /idea-iter <idea>          Idea -> papers -> code -> launch experiment
    /check-experiments         Check running experiments, collect results
    /combine-findings <input>  Integrate a paper/idea into current work

  Learn more: https://github.com/haoyudong-97/idea2code
`);
}

export async function main() {
  const args = process.argv.slice(2);

  if (args.includes('--help') || args.includes('-h')) {
    showHelp();
    return;
  }

  if (args.includes('--uninstall') || args.includes('--remove')) {
    await uninstallSkills();
    return;
  }

  installSkills();
}
