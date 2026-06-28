export type Stylable<T extends string = never> = {
  [key in `${T}ClassName`]?: string;
} & {
  className?: string;
};
