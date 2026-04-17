/** Jest config for renderer unit tests (tsx + React). */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "jsdom",
  testMatch: ["<rootDir>/tests/unit/**/*.test.ts?(x)"],
  moduleNameMapper: {
    "^@shared/(.*)$": "<rootDir>/src/shared/$1",
    "\\.(css|less|scss)$": "<rootDir>/tests/unit/__mocks__/styleMock.js",
  },
  setupFilesAfterEnv: ["<rootDir>/tests/unit/setup.ts"],
  globals: {
    "ts-jest": {
      tsconfig: {
        target: "ES2022",
        module: "CommonJS",
        jsx: "react-jsx",
        esModuleInterop: true,
        resolveJsonModule: true,
        skipLibCheck: true,
      },
    },
  },
  transform: { "^.+\\.tsx?$": ["ts-jest", {}] },
};
