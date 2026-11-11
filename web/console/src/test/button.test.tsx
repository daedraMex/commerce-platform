import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "@/components/atoms/button";

describe("Button", () => {
  it("renders its label", () => {
    render(<Button>Quetzal</Button>);

    expect(screen.getByRole("button", { name: "Quetzal" })).toBeInTheDocument();
  });
});
