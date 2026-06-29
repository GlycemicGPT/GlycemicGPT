import { readFileSync } from "node:fs";
import { join } from "node:path";

type CssDeclaration = {
  line: number;
  name: string;
  value: string;
};

const colorsPath = join(process.cwd(), "src/styles/config/colors.css");
const themePath = join(process.cwd(), "src/styles/config/theme.css");

function readCss(path: string) {
  return readFileSync(path, "utf8");
}

function lineNumberForIndex(content: string, index: number) {
  return content.slice(0, index).split("\n").length;
}

function getColorDeclarations(content: string): CssDeclaration[] {
  const declarationPattern = /(--color-[a-z0-9-]+)\s*:\s*([^;]+);/g;
  const declarations: CssDeclaration[] = [];

  for (const match of content.matchAll(declarationPattern)) {
    declarations.push({
      line: lineNumberForIndex(content, match.index ?? 0),
      name: match[1],
      value: match[2].trim(),
    });
  }

  return declarations;
}

function formatDeclaration(declaration: CssDeclaration) {
  return `theme.css:${declaration.line} ${declaration.name}: ${declaration.value};`;
}

const colorsCss = readCss(colorsPath);
const themeCss = readCss(themePath);
const baseColorNames = new Set(
  getColorDeclarations(colorsCss).map((declaration) => declaration.name),
);
const themeDeclarations = getColorDeclarations(themeCss);
const errors: string[] = [];

for (const declaration of themeDeclarations) {
  const normalizedValue = declaration.value.replace(/\s+/g, " ");
  const varReference = normalizedValue.match(/^var\(\s*(--color-[a-z0-9-]+)\s*\)$/);

  if (!varReference) {
    errors.push(
      `${formatDeclaration(declaration)} must reference a color from colors.css with var(--color-base-...).`,
    );
    continue;
  }

  const referencedColor = varReference[1];

  if (!baseColorNames.has(referencedColor)) {
    errors.push(
      `${formatDeclaration(declaration)} references ${referencedColor}, which is not defined in colors.css.`,
    );
  }
}

if (errors.length > 0) {
  console.error("Theme color validation failed:\n");
  console.error(errors.map((error) => `- ${error}`).join("\n"));
  process.exit(1);
}

console.log(
  `Theme color validation passed for ${themeDeclarations.length} theme color variables.`,
);
