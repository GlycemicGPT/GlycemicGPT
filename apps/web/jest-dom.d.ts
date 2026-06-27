// Makes @testing-library/jest-dom's custom matcher type augmentations
// (toBeInTheDocument, toHaveAttribute, toHaveTextContent, ...) visible to `tsc`
// for every test file. The runtime import lives in jest.setup.js, but that is a
// .js file the tsconfig `include` (**/*.ts / **/*.tsx) does not pick up, so its
// global augmentation was invisible to the type-checker and every matcher call
// in __tests__/ reported "Property '...' does not exist on JestMatchers". This
// side-effect import loads those augmentations into the TS program.
import "@testing-library/jest-dom";
